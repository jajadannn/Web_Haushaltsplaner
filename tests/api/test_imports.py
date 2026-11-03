"""Import: Upload, Verarbeitung, Dubletten, Klärung, Fehler/Wiederholung, Kontozuordnung, Kreditraten."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import ImportBatch
from app.services import import_jobs

IBAN_A = "DE89370400440532013000"
IBAN_B = "DE02120300000000202051"
LENDER_IBAN = "DE02500105170137075030"
HEADER = "Auftragskonto;Buchungstag;Valutadatum;Empfänger/Auftraggeber;IBAN;Verwendungszweck;Betrag;Waehrung"
COLUMN_MAP = {
    "own_account": "Auftragskonto",
    "booking_date": "Buchungstag",
    "value_date": "Valutadatum",
    "counterparty": "Empfänger/Auftraggeber",
    "counterparty_iban": "IBAN",
    "description": "Verwendungszweck",
    "amount": "Betrag",
    "currency": "Waehrung",
}


def csv_file(*rows, account=IBAN_A) -> bytes:
    """rows: (datum, betrag, text[, gegenpartei[, iban[, währung]]])"""
    lines = [HEADER]
    for row in rows:
        day, amount, text, *rest = row
        counterparty = rest[0] if rest else "Händler"
        iban = rest[1] if len(rest) > 1 else ""
        currency = rest[2] if len(rest) > 2 else "EUR"
        lines.append(f"{account};{day};{day};{counterparty};{iban};{text};{amount};{currency}")
    return ("\n".join(lines) + "\n").encode()


@pytest.fixture
def bank(make_institution):
    return make_institution("Sparkasse")


@pytest.fixture
def giro(make_account, bank):
    return make_account("Giro", institution_id=bank["id"], iban=IBAN_A, opening_balance_date="2026-01-01")


@pytest.fixture
def profile(client, headers, bank):
    response = client.post(
        "/import-profiles",
        json={"name": "Sparkasse CSV", "institution_id": bank["id"], "format": "csv", "column_map": COLUMN_MAP},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, headers, profile, content, name="umsaetze.csv", account_id=None, process=True):
    data = {"import_profile_id": str(profile["id"])}
    if account_id is not None:
        data["account_id"] = str(account_id)
    response = client.post("/imports", data=data, files={"file": (name, content, "text/csv")}, headers=headers)
    assert response.status_code in (200, 202), response.text
    if process:
        client.post("/imports/process", headers=headers)
        return client.get(f"/imports/{response.json()['id']}", headers=headers).json()
    return response.json()


def rows(client, headers, batch, **params):
    return client.get(f"/imports/{batch['id']}/rows", params=params, headers=headers).json()


def resolve(client, headers, batch, **payload):
    response = client.post(f"/imports/{batch['id']}/rows/resolve", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def commit(client, headers, batch):
    return client.post(f"/imports/{batch['id']}/commit", headers=headers)


def transactions(client, headers, **params):
    return client.get("/transactions", params={"limit": 200, **params}, headers=headers).json()["items"]


def balance(client, headers, account_id):
    return client.get(f"/accounts/{account_id}", params={"as_of": "2099-12-31"}, headers=headers).json()["balance"]


JANUAR = (
    ("02.01.2026", "-12,34", "Einkauf", "REWE"),
    ("03.01.2026", "2.500,00", "Gehalt Januar", "Arbeitgeber GmbH"),
    ("05.01.2026", "-3,50", "Brötchen", "Bäckerei Krume"),
    ("05.01.2026", "-3,50", "Brötchen", "Bäckerei Krume"),  # zweite, echte Zahlung
)


# --- Grundablauf ---------------------------------------------------------------


def test_upload_verarbeitung_und_archiv(client, headers, profile, giro, import_dir):
    queued = upload(client, headers, profile, csv_file(*JANUAR), process=False)
    assert queued["status"] == "queued" and queued["source"] == "upload"
    assert client.post("/imports/process", headers=headers).json() == {"processed": 1}

    batch = client.get(f"/imports/{queued['id']}", headers=headers).json()
    assert batch["status"] == "done" and batch["account_id"] == giro["id"]
    assert (batch["rows_total"], batch["rows_new"], batch["rows_review"]) == (4, 4, 0)
    assert batch["archive_state"] == "done"
    assert (import_dir / "archive" / f"{batch['id']}_umsaetze.csv").exists()
    assert not any((import_dir / "processing").iterdir())

    txs = transactions(client, headers)
    assert len(txs) == 4  # beide Bäckerei-Zahlungen bleiben erhalten
    assert {t["source"] for t in txs} == {"import"}
    assert {t["review_status"] for t in txs} == {"needs_review"}
    gehalt = next(t for t in txs if t["amount"] == "2500.00")
    assert gehalt["counterparty"] == "Arbeitgeber GmbH" and gehalt["description"] == "Gehalt Januar"
    assert balance(client, headers, giro["id"]) == "3480.66"  # 1000 − 12,34 + 2500 − 7,00


def test_gleiche_datei_nur_einmal(client, headers, profile, giro):
    first = upload(client, headers, profile, csv_file(*JANUAR))
    response = client.post(
        "/imports", data={"import_profile_id": str(profile["id"])},
        files={"file": ("nochmal.csv", csv_file(*JANUAR), "text/csv")}, headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == first["id"] and response.json()["already_imported"] is True
    assert len(transactions(client, headers)) == 4


def test_ueberlappender_export_wird_geklaert(client, headers, profile, giro):
    upload(client, headers, profile, csv_file(*JANUAR))
    second = upload(client, headers, profile, csv_file(*JANUAR[2:], ("10.01.2026", "-20,00", "Tanken", "Tankstelle")))
    assert second["status"] == "awaiting_review" and second["rows_review"] == 2

    open_rows = rows(client, headers, second, open_only=True)
    assert {r["match_kind"] for r in open_rows} == {"fingerprint"}
    assert len({r["matched_transaction_id"] for r in open_rows}) == 2  # je Zeile eine andere Buchung
    assert commit(client, headers, second).json()["error"]["code"] == "import_rows_open"

    result = resolve(client, headers, second, action="duplicate", decision="ambiguous", match_kind="fingerprint")
    assert result == {"resolved": 2, "open_rows": 0}
    done = commit(client, headers, second).json()
    assert (done["status"], done["rows_new"], done["rows_duplicate"]) == ("done", 1, 2)
    assert len(transactions(client, headers)) == 5


def test_teil_exporte_mit_identischer_zahlung_gehen_nicht_verloren(client, headers, profile, giro):
    baecker = ("20.01.2026", "-3,50", "Brötchen", "Bäckerei Krume")
    upload(client, headers, profile, csv_file(baecker, ("21.01.2026", "-1,00", "A")))
    second = upload(client, headers, profile, csv_file(baecker, ("22.01.2026", "-2,00", "B")))
    row = rows(client, headers, second, open_only=True)[0]
    assert row["match_kind"] == "fingerprint"
    # Nutzer weiß: das ist eine zweite, echte Zahlung
    resolve(client, headers, second, action="import", row_ids=[row["id"]])
    assert commit(client, headers, second).json()["status"] == "done"
    assert len([t for t in transactions(client, headers) if t["amount"] == "-3.50"]) == 2


def test_manuell_erfasste_zahlung_wird_erkannt(client, headers, profile, giro):
    kat = client.post("/categories", json={"name": "Brot", "type": "expense"}, headers=headers).json()
    manual = client.post(
        "/transactions",
        json={"account_id": giro["id"], "booking_date": "2026-01-04", "amount": "-3.50",
              "description": "Bäcker", "category_id": kat["id"]},
        headers=headers,
    ).json()
    batch = upload(client, headers, profile, csv_file(("05.01.2026", "-3,50", "Brötchen", "Bäckerei Krume")))
    row = rows(client, headers, batch, open_only=True)[0]
    assert (row["match_kind"], row["matched_transaction_id"]) == ("similar", manual["id"])
    resolve(client, headers, batch, action="duplicate", row_ids=[row["id"]])
    commit(client, headers, batch)

    txs = transactions(client, headers)
    assert len(txs) == 1 and txs[0]["category_id"] == kat["id"]  # manuelle Kategorie bleibt
    # Jetzt mit Importidentität: nicht mehr löschbar, nur ausschließbar
    response = client.delete(f"/transactions/{manual['id']}", headers=headers)
    assert response.json()["error"]["code"] == "imported_use_exclude"


def test_ausgeschlossene_buchung_kommt_nicht_still_zurueck(client, headers, profile, giro):
    upload(client, headers, profile, csv_file(("02.01.2026", "-12,34", "Einkauf", "REWE")))
    tx = transactions(client, headers)[0]
    client.post(f"/transactions/{tx['id']}/exclude", json={"reason": "Fehlbuchung"}, headers=headers)
    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-12,34", "Einkauf", "REWE"), ("03.01.2026", "-1,00", "X")))
    row = rows(client, headers, batch, open_only=True)[0]
    assert row["matched_transaction_id"] == tx["id"]
    resolve(client, headers, batch, action="duplicate", decision="ambiguous")
    commit(client, headers, batch)
    assert len(transactions(client, headers)) == 1
    assert len(transactions(client, headers, include_excluded=True)) == 2


# --- Stichtag, Fehler, Wiederholung ----------------------------------------------


def test_zeilen_vor_dem_stichtag(client, headers, profile, giro):
    batch = upload(client, headers, profile, csv_file(("30.12.2025", "-5,00", "Alt"), ("02.01.2026", "-1,00", "Neu")))
    assert batch["status"] == "awaiting_review"
    alt = rows(client, headers, batch, decision="before_opening")[0]
    response = client.post(f"/imports/{batch['id']}/rows/resolve",
                           json={"action": "import", "row_ids": [alt["id"]]}, headers=headers)
    assert response.json()["error"]["code"] == "before_opening"
    resolve(client, headers, batch, action="skip", decision="before_opening")
    assert commit(client, headers, batch).json()["rows_skipped"] == 1
    assert [t["description"] for t in transactions(client, headers)] == ["Neu"]


def test_formatfehler_nichts_gebucht_und_wiederholbar(client, headers, profile, giro, import_dir):
    client.patch(f"/import-profiles/{profile['id']}", json={"date_format": "%Y-%m-%d"}, headers=headers)
    batch = upload(client, headers, profile, csv_file(*JANUAR))
    assert batch["status"] == "failed" and batch["errors"][0]["code"] == "row_errors"
    assert len(batch["errors"][0]["details"]) == 4
    assert transactions(client, headers) == []
    assert (import_dir / "failed" / f"{batch['id']}_umsaetze.csv").exists()

    fixed = client.patch(f"/import-profiles/{profile['id']}", json={"date_format": "%d.%m.%Y"}, headers=headers).json()
    assert fixed["version"] == 3
    assert client.post(f"/imports/{batch['id']}/retry", headers=headers).json()["status"] == "queued"
    client.post("/imports/process", headers=headers)
    batch = client.get(f"/imports/{batch['id']}", headers=headers).json()
    assert (batch["status"], batch["attempt"], batch["profile_version"]) == ("done", 2, 3)
    assert (import_dir / "archive" / f"{batch['id']}_umsaetze.csv").exists()
    assert len(transactions(client, headers)) == 4


def test_fremdwaehrung_abgewiesen(client, headers, profile, giro):
    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-12,34", "Einkauf", "Shop", "", "USD")))
    assert batch["status"] == "failed"
    assert "USD" in batch["errors"][0]["details"][0]["message"]


def test_vorgemerkte_umsaetze_werden_uebersprungen(client, headers, bank, giro):
    profile = client.post(
        "/import-profiles",
        json={"name": "Mit Status", "institution_id": bank["id"], "format": "csv",
              "column_map": {**COLUMN_MAP, "status": "Waehrung"}, "pending_values": ["VORGEMERKT"]},
        headers=headers,
    ).json()
    content = csv_file(("02.01.2026", "-1,00", "A"), ("03.01.2026", "-2,00", "B", "X", "", "VORGEMERKT"))
    batch = upload(client, headers, profile, content)
    assert (batch["status"], batch["rows_total"], batch["rows_pending"]) == ("done", 1, 1)


# --- Kontozuordnung: mehrere Konten, gleiche Bank -------------------------------


def test_mehrkontodatei_wird_je_iban_zugeordnet(client, headers, profile, giro, bank, make_account):
    sparen = make_account("Sparkonto", type="savings", institution_id=bank["id"], iban=IBAN_B,
                          opening_balance="0", opening_balance_date="2026-01-01")
    content = csv_file(("02.01.2026", "-10,00", "Giro-Umsatz")) + csv_file(
        ("02.01.2026", "50,00", "Spar-Umsatz"), account=IBAN_B
    ).split(b"\n", 1)[1]
    batch = upload(client, headers, profile, content)
    assert batch["status"] == "done" and batch["account_id"] is None
    assert balance(client, headers, giro["id"]) == "990.00"
    assert balance(client, headers, sparen["id"]) == "50.00"


def test_konto_widerspricht_auswahl(client, headers, profile, giro, bank, make_account):
    sparen = make_account("Sparkonto", type="savings", institution_id=bank["id"], iban=IBAN_B)
    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-10,00", "X")), account_id=sparen["id"])
    assert batch["status"] == "failed" and batch["errors"][0]["code"] == "account_mismatch"
    response = client.post(f"/imports/{batch['id']}/retry", json={"account_id": giro["id"]}, headers=headers)
    assert response.status_code == 200
    client.post("/imports/process", headers=headers)
    assert client.get(f"/imports/{batch['id']}", headers=headers).json()["status"] == "done"


def test_unbekanntes_konto(client, headers, profile, giro):
    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-10,00", "X"), account=IBAN_B))
    assert batch["errors"][0]["code"] == "unknown_accounts"
    assert batch["errors"][0]["details"] == {"accounts": [IBAN_B]}


def mt940_file(account: str) -> bytes:
    return (
        f":20:STARTUMS\r\n:25:{account}\r\n:28C:00001/001\r\n:60F:C260101EUR100,00\r\n"
        ":61:2601020102D10,00NTRFNONREF\r\n:86:166?00ÜBERWEISUNG?20Testbuchung\r\n"
        ":62F:C260131EUR90,00\r\n-\r\n"
    ).encode()


@pytest.fixture
def mt940_profile(client, headers, bank):
    response = client.post("/import-profiles", json={"name": "MT940", "institution_id": bank["id"], "format": "mt940"},
                           headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("account_id_given", [False, True])
def test_mt940_mit_blz_und_kontonummer_findet_konto_mit_iban(client, headers, mt940_profile, giro, account_id_given):
    """:25:37040044/0532013000 gehört zum Konto mit IBAN DE89370400440532013000."""
    batch = upload(client, headers, mt940_profile, mt940_file("37040044/0532013000"), name="auszug.sta",
                   account_id=giro["id"] if account_id_given else None)
    assert batch["status"] == "done", batch["errors"]
    assert balance(client, headers, giro["id"]) == "990.00"


def test_mt940_konto_nur_mit_kontonummer_angelegt(client, headers, mt940_profile, bank, make_account):
    konto = make_account("Giro alt", institution_id=bank["id"], bank_account_ref="532013000",
                         opening_balance="0", opening_balance_date="2026-01-01")
    batch = upload(client, headers, mt940_profile, mt940_file("37040044/0532013000"), name="auszug.sta")
    assert batch["status"] == "done", batch["errors"]
    assert balance(client, headers, konto["id"]) == "-10.00"


def test_mt940_fremdes_konto_nennt_die_kontoangabe(client, headers, mt940_profile, giro):
    batch = upload(client, headers, mt940_profile, mt940_file("12030000/0000202051"), name="auszug.sta")
    error = batch["errors"][0]
    assert error["code"] == "unknown_accounts" and error["details"] == {"accounts": [IBAN_B]}
    assert IBAN_B in error["message"]


def test_konto_einer_anderen_bank_als_auswahl_abgelehnt(client, headers, profile, make_institution, make_account):
    andere = make_institution("DKB")
    konto = make_account("DKB Giro", institution_id=andere["id"])
    response = client.post(
        "/imports", data={"import_profile_id": str(profile["id"]), "account_id": str(konto["id"])},
        files={"file": ("x.csv", csv_file(("02.01.2026", "-1,00", "X")), "text/csv")}, headers=headers,
    )
    assert response.json()["error"]["code"] == "institution_mismatch"


# --- OFX mit Bank-IDs -----------------------------------------------------------


def ofx_file(*transactions_) -> bytes:
    items = "".join(
        f"<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>{day}<TRNAMT>{amount}<FITID>{fitid}<NAME>{name}<MEMO>{name}</STMTTRN>"
        for day, amount, fitid, name in transactions_
    )
    return (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\nCHARSET:1252\n"
        "COMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
        "<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20260131"
        "<LANGUAGE>GER</SONRS></SIGNONMSGSRSV1><BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0"
        "<SEVERITY>INFO</STATUS><STMTRS><CURDEF>EUR<BANKACCTFROM><BANKID>37040044"
        f"<ACCTID>{IBAN_A}<ACCTTYPE>CHECKING</BANKACCTFROM><BANKTRANLIST><DTSTART>20260101<DTEND>20260131"
        f"{items}</BANKTRANLIST><LEDGERBAL><BALAMT>0<DTASOF>20260131</LEDGERBAL></STMTRS></STMTTRNRS>"
        "</BANKMSGSRSV1></OFX>\n"
    ).encode()


def test_ofx_bank_id_erkennt_dubletten_ohne_rueckfrage(client, headers, bank, giro):
    profile = client.post("/import-profiles", json={"name": "OFX", "institution_id": bank["id"], "format": "ofx"},
                          headers=headers).json()
    upload(client, headers, profile, ofx_file(("20260102", "-12.34", "F1", "REWE"), ("20260103", "-5.00", "F2", "DM")))
    second = upload(client, headers, profile, ofx_file(("20260103", "-5.00", "F2", "DM"), ("20260104", "-5.00", "F3", "DM")))
    assert (second["status"], second["rows_duplicate"], second["rows_new"]) == ("done", 1, 1)
    assert len(transactions(client, headers)) == 3

    conflict = upload(client, headers, profile, ofx_file(("20260104", "-7.00", "F3", "DM")))
    row = rows(client, headers, conflict)[0]
    assert (conflict["status"], row["decision"], row["match_kind"]) == ("awaiting_review", "ambiguous", "external_id")


def test_erneute_pruefung_beim_uebernehmen(client, headers, bank, giro):
    """Zwei offene Importe mit derselben Bank-ID: der zweite wird beim Übernehmen erneut geprüft."""
    profile = client.post("/import-profiles", json={"name": "OFX", "institution_id": bank["id"], "format": "ofx"},
                          headers=headers).json()
    client.post("/transactions", json={"account_id": giro["id"], "booking_date": "2026-01-09", "amount": "-9.99",
                                       "description": "manuell"}, headers=headers)
    first = upload(client, headers, profile, ofx_file(("20260109", "-9.99", "X1", "Abo"), ("20260110", "-1.00", "X2", "A")))
    second = upload(client, headers, profile, ofx_file(("20260110", "-1.00", "X2", "A"), ("20260109", "-9.99", "X1", "Abo"), ("20260111", "-2.00", "X3", "B")))
    assert first["status"] == second["status"] == "awaiting_review"
    resolve(client, headers, first, action="import", decision="ambiguous")
    resolve(client, headers, second, action="import", decision="ambiguous")
    assert commit(client, headers, first).json()["status"] == "done"
    response = commit(client, headers, second)
    assert response.status_code == 409 and response.json()["error"]["code"] == "import_new_conflicts"
    assert client.get(f"/imports/{second['id']}", headers=headers).json()["status"] == "awaiting_review"


# --- Kreditraten im Import -------------------------------------------------------


def _loan(client, headers, giro, **extra):
    payload = {"name": "Autokredit", "loan_type": "annuity", "lender_name": "Autobank", "lender_iban": LENDER_IBAN,
               "annual_interest_rate": "5", "current_balance": "10000.00", "balance_date": "2026-01-01",
               "first_due_date": "2026-01-30", "term_months": 48, "payment_account_id": giro["id"], **extra}
    response = client.post("/loans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_kreditrate_wird_automatisch_erkannt(client, headers, profile, giro):
    loan = _loan(client, headers, giro)
    batch = upload(client, headers, profile, csv_file(("31.01.2026", "-230,30", "Rate 1", "Autobank", LENDER_IBAN)))
    assert batch["status"] == "done"
    view = client.get(f"/loans/{loan['id']}", headers=headers).json()
    assert view["remaining_debt"] == "9811.37"
    tx = transactions(client, headers, account_ids=[giro["id"]])[0]
    assert tx["category_source"] == "loan" and len(tx["splits"]) == 2
    assert client.get(f"/loans/{loan['id']}/schedule", headers=headers).json()[0]["status"] == "paid"


def test_kreditrate_mit_abweichendem_betrag_nur_vorschlag(client, headers, profile, giro):
    loan = _loan(client, headers, giro)
    batch = upload(client, headers, profile, csv_file(("31.01.2026", "-230,00", "Rate 1", "Autobank", LENDER_IBAN)))
    row = rows(client, headers, batch)[0]
    first_entry = client.get(f"/loans/{loan['id']}/schedule", headers=headers).json()[0]
    assert row["suggested_loan_entry_id"] is not None and first_entry["status"] == "planned"
    tx = transactions(client, headers)[0]
    assert tx["review_status"] == "needs_review"
    # Vorschlag annehmen: Rate mit der vorhandenen Buchung verknüpfen
    response = client.post(f"/loans/{loan['id']}/payments", json={"transaction_id": tx["id"]}, headers=headers)
    assert response.status_code == 201
    assert response.json()["principal"] == "188.33"  # 230,00 − 41,67 Zinsen


# --- Worker, Wiederanlauf, Isolation ---------------------------------------------


def test_watcher_uebernimmt_datei_aus_inbox(client, headers, profile, giro, session, import_dir):
    from app.worker import ingest_inbox_file, is_candidate

    folder = client.post("/watch-folders", json={"subdir": "sparkasse", "import_profile_id": profile["id"]},
                         headers=headers).json()
    inbox = import_dir / "inbox"
    assert folder["path"] == str(inbox / "sparkasse")
    part = inbox / "sparkasse" / "januar.csv.part"
    part.write_bytes(csv_file(*JANUAR))
    assert not is_candidate(part, inbox)
    final = part.with_name("januar.csv")
    part.rename(final)
    assert is_candidate(final, inbox)

    batch_id = ingest_inbox_file(session, final, inbox)
    assert not final.exists()
    import_jobs.process_queue(session)
    batch = client.get(f"/imports/{batch_id}", headers=headers).json()
    assert (batch["status"], batch["source"]) == ("done", "watcher")
    assert (import_dir / "archive" / f"{batch_id}_januar.csv").exists()

    # Dieselbe Datei erneut abgelegt: kein neuer Auftrag, Datei wird als Dublette archiviert
    again = inbox / "sparkasse" / "januar-kopie.csv"
    again.write_bytes(csv_file(*JANUAR))
    assert ingest_inbox_file(session, again, inbox) == batch_id
    assert any("bereits-importiert" in p.name for p in (import_dir / "archive").iterdir())
    assert len(transactions(client, headers)) == 4


def test_unbekannter_inbox_ordner(session, import_dir):
    from app.worker import ingest_inbox_file

    path = import_dir / "inbox" / "gibtsnicht" / "x.csv"
    path.parent.mkdir(parents=True)
    path.write_text("x")
    assert ingest_inbox_file(session, path, import_dir / "inbox") is None
    assert (import_dir / "failed" / "unbekannter-ordner_gibtsnicht_x.csv").exists()


def test_haengengebliebene_auftraege_werden_neu_eingereiht(client, headers, profile, giro, session):
    queued = upload(client, headers, profile, csv_file(*JANUAR), process=False)
    batch = session.get(ImportBatch, queued["id"])
    batch.status, batch.heartbeat_at = "processing", datetime.now(UTC) - timedelta(hours=1)
    session.commit()
    assert import_jobs.requeue_stale(session) == 1
    assert import_jobs.process_queue(session) == 1
    assert client.get(f"/imports/{queued['id']}", headers=headers).json()["status"] == "done"


def test_archivierungsfehler_wird_nachgeholt(client, headers, profile, giro, session, import_dir, monkeypatch):
    calls = {"n": 0}
    real_replace = import_jobs.os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("Platte voll")
        return real_replace(src, dst)

    queued = upload(client, headers, profile, csv_file(*JANUAR), process=False)
    monkeypatch.setattr(import_jobs.os, "replace", flaky_replace)
    client.post("/imports/process", headers=headers)
    batch = client.get(f"/imports/{queued['id']}", headers=headers).json()
    assert (batch["status"], batch["archive_state"]) == ("done", "error")  # Buchungen bleiben gültig
    assert len(transactions(client, headers)) == 4
    assert import_jobs.archive_pending(session) == 1
    assert client.get(f"/imports/{batch['id']}", headers=headers).json()["archive_state"] == "done"


def test_profil_isolation(client, headers, profile, giro, other_user):
    batch = upload(client, headers, profile, csv_file(*JANUAR))
    fremd = other_user["headers"]
    assert client.get(f"/imports/{batch['id']}", headers=fremd).status_code == 404
    assert client.get(f"/imports/{batch['id']}/rows", headers=fremd).status_code == 404
    assert client.get(f"/import-profiles/{profile['id']}", headers=fremd).status_code == 404
    assert client.get("/imports", headers=fremd).json() == []
    response = client.post("/imports", data={"import_profile_id": str(profile["id"])},
                           files={"file": ("x.csv", b"x", "text/csv")}, headers=fremd)
    assert response.status_code == 404


def test_profilvalidierung(client, headers, bank):
    cases = [
        {"column_map": {"booking_date": "A"}},  # Betrag fehlt
        {"column_map": {**COLUMN_MAP, "foo": "X"}},
        {"column_map": COLUMN_MAP, "encoding": "klingonisch"},
        {"column_map": COLUMN_MAP, "date_format": "TT.MM.JJJJ"},
        {"column_map": COLUMN_MAP, "decimal_sep": ".", "thousands_sep": "."},
        {"column_map": {"booking_date": "A", "amount": "B", "indicator": "C"}, "sign_mode": "indicator_column"},
    ]
    for extra in cases:
        payload = {"name": "P", "institution_id": bank["id"], "format": "csv", **extra}
        assert client.post("/import-profiles", json=payload, headers=headers).status_code == 422, extra
