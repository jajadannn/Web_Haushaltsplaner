"""Regressionstests zu docs/PRUEFBERICHT_2026-11-02.md – je Befund der dort beschriebene Nachweis."""

import os
import subprocess
from pathlib import Path

import pytest

from app.config import get_settings
from app.models import ImportBatch
from app.services import import_jobs
from tests.api.test_imports import COLUMN_MAP, IBAN_A, IBAN_B, csv_file, resolve, rows, upload

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bank(make_institution):
    return make_institution("Sparkasse")


@pytest.fixture
def giro(make_account, bank):
    return make_account("Giro", institution_id=bank["id"], iban=IBAN_A, opening_balance="5000.00")


@pytest.fixture
def profile(client, headers, bank):
    return client.post("/import-profiles", json={"name": "CSV", "institution_id": bank["id"], "format": "csv",
                                                 "column_map": COLUMN_MAP}, headers=headers).json()


def _loan(client, headers, **extra):
    payload = {"name": "Kredit", "loan_type": "annuity", "lender_name": "Bank", "annual_interest_rate": "12",
               "current_balance": "1000.00", "balance_date": "2026-01-01", "first_due_date": "2026-01-31",
               "term_months": 12, **extra}
    response = client.post("/loans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _balance(client, headers, account_id):
    return client.get(f"/accounts/{account_id}", params={"as_of": "2099-12-31"}, headers=headers).json()["balance"]


# 1 – Importfreigabe gesperrt und idempotent
def test_1_freigabe_sieht_frischen_status_und_bucht_nie_doppelt(client, headers, profile, giro, session, user):
    from app.models import User
    from app.services.import_commit import commit_batch

    client.post("/transactions", json={"account_id": giro["id"], "booking_date": "2026-01-02", "amount": "-10.00",
                                       "description": "manuell"}, headers=headers)
    batch = upload(client, headers, profile, csv_file(("02.01.2026", "-10,00", "Kauf")))
    resolve(client, headers, batch, action="import", decision="ambiguous")
    stale = session.get(ImportBatch, batch["id"])  # Session B liest den Auftrag vorab
    assert stale.status == "awaiting_review"
    assert client.post(f"/imports/{batch['id']}/commit", headers=headers).json()["status"] == "done"

    locked = import_jobs.lock_batch(session, session.get(User, user["id"]), batch["id"])
    assert locked.status == "done"  # frischer Stand trotz zuvor geladener Instanz
    commit_batch(session, session.get(User, user["id"]), locked)  # erneuter Durchlauf bucht nichts
    session.flush()
    amounts = [t["amount"] for t in client.get("/transactions", headers=headers).json()["items"]]
    assert amounts.count("-10.00") == 2  # manuelle Buchung + genau eine importierte
    assert client.post(f"/imports/{batch['id']}/commit", headers=headers).status_code == 409


# 2 – Kein Markup aus Nutzertexten im PDF
def test_2_pdf_wertet_markup_in_namen_nicht_aus(client, headers, user, tmp_path):
    picture = tmp_path / "x.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    client.patch(f"/users/{user['id']}", json={"name": f'<img src="{picture}" width="10" height="10"/>'})
    response = client.get("/export/report.pdf", params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
                          headers=headers)
    assert response.status_code == 200
    assert b"/Subtype /Image" not in response.content
    loan = _loan(client, headers, lender_name='<font name="Nope">Bank</font>')
    assert client.get(f"/export/loans/{loan['id']}/schedule.pdf", headers=headers).status_code == 200


# 3 – Prüfliste respektiert gekoppelte Umbuchungen
def test_3_pruefliste_macht_keine_umbuchungsseite_zur_ausgabe(client, headers, make_account):
    a, b = make_account("A"), make_account("B")
    kat = client.post("/categories", json={"name": "X", "type": "expense"}, headers=headers).json()
    out = client.post("/transfers", json={"from_account_id": a["id"], "to_account_id": b["id"],
                                          "booking_date": "2026-01-05", "amount": "100.00"},
                      headers=headers).json()["outgoing"]
    response = client.post(f"/review/{out['id']}/confirm", json={"category_id": kat["id"]}, headers=headers)
    assert response.json()["error"]["code"] == "transfer_pair_linked"
    response = client.post("/review/bulk-confirm", json={"transaction_ids": [out["id"]], "category_id": kat["id"]},
                           headers=headers)
    assert response.json()["error"]["code"] == "transfer_pair_linked"
    assert client.get(f"/transactions/{out['id']}", headers=headers).json()["kind"] == "transfer"


# 4 – Raten nur in Reihenfolge
def test_4_spaetere_rate_verdraengt_keine_offene_rate(client, headers, giro):
    loan = _loan(client, headers, payment_account_id=giro["id"])
    response = client.post(f"/loans/{loan['id']}/payments",
                           json={"booking_date": "2026-02-28", "amount": "88.85", "schedule_seq": 2}, headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "installment_not_next"
    plan = client.get(f"/loans/{loan['id']}/schedule", headers=headers).json()
    assert plan[0]["seq"] == 1 and plan[0]["status"] == "planned"


# 5 – Kreditkonto-Basisfelder nur über /loans
def test_5_restschuld_nicht_ueber_kontobearbeitung(client, headers):
    loan = _loan(client, headers)
    response = client.patch(f"/accounts/{loan['account_id']}", json={"opening_balance": "-2000.00"}, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "loan_account_via_loans"
    assert client.patch(f"/accounts/{loan['account_id']}", json={"name": "Umbenannt"}, headers=headers).status_code == 200


# 6 – Teilzahlung unter den fälligen Zinsen
def test_6_teilzahlung_laesst_zinsen_nicht_verschwinden(client, headers, giro):
    loan = _loan(client, headers, payment_account_id=giro["id"])
    response = client.post(f"/loans/{loan['id']}/payments", json={"booking_date": "2026-01-31", "amount": "1.00"},
                           headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "payment_below_interest"
    assert client.get(f"/loans/{loan['id']}/schedule", headers=headers).json()[0]["status"] == "planned"


# 7 – Rückdatierte Zahlungen
def test_7_rueckdatierte_privatkreditzahlung_abgelehnt(client, headers, giro):
    loan = _loan(client, headers, loan_type="private", annual_interest_rate="3.65", term_months=None,
                 payment_account_id=giro["id"])
    first = client.post(f"/loans/{loan['id']}/payments", json={"booking_date": "2026-04-11", "amount": "110.00"},
                        headers=headers).json()
    assert (first["interest"], first["principal"]) == ("10.00", "100.00")
    response = client.post(f"/loans/{loan['id']}/payments", json={"booking_date": "2026-02-01", "amount": "100.00"},
                           headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "payment_backdated"


# 8 – Dateiidentität mit Zielkonto
def test_8_gleiche_datei_fuer_zwei_konten_derselben_bank(client, headers, bank, giro, make_account):
    profile = client.post("/import-profiles", json={
        "name": "Ohne Kontospalte", "institution_id": bank["id"], "format": "csv",
        "column_map": {k: v for k, v in COLUMN_MAP.items() if k != "own_account"}}, headers=headers).json()
    sparen = make_account("Sparen", type="savings", institution_id=bank["id"], iban=IBAN_B, opening_balance="0")
    content = csv_file(("02.01.2026", "-10,00", "Gebühr"))
    first = upload(client, headers, profile, content, account_id=giro["id"])
    second = upload(client, headers, profile, content, account_id=sparen["id"])
    assert first["id"] != second["id"] and second["status"] == "done"
    assert _balance(client, headers, sparen["id"]) == "-10.00"
    again = upload(client, headers, profile, content, account_id=sparen["id"], process=False)
    assert again["id"] == second["id"] and again["already_imported"] is True


# 9 – Abgebrochene Verarbeitung bleibt wiederaufnehmbar
def test_9_abbruch_waehrend_der_verarbeitung_laesst_nichts_haengen(client, headers, profile, giro, session):
    queued = upload(client, headers, profile, csv_file(("02.01.2026", "-1,00", "X")), process=False)
    batch_id = import_jobs.claim_next(session)
    assert batch_id == queued["id"]
    session.rollback()  # Prozess stirbt vor dem Commit
    assert session.get(ImportBatch, batch_id).status == "queued"
    # Ein (alt-)gespeichertes `processing` wird unabhängig vom Alter wieder eingereiht
    batch = session.get(ImportBatch, batch_id)
    batch.status = "processing"
    session.commit()
    assert import_jobs.requeue_stale(session) == 1
    assert import_jobs.process_queue(session) == 1
    assert session.get(ImportBatch, batch_id).status == "done"


# 10 – Regex-Größe vor dem Kompilieren begrenzt
@pytest.mark.parametrize("pattern", ["x{1000000000}", "a{51}", "(a{5}){5}{5}"])
def test_10_aufwendige_regex_abgelehnt(client, headers, pattern):
    kat = client.post("/categories", json={"name": "R", "type": "expense"}, headers=headers).json()
    response = client.post("/mapping-rules", json={"pattern": pattern, "match_type": "regex",
                                                   "target_category_id": kat["id"]}, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "regex_too_complex"


# 11 – Uploadlimit vor der Multipart-Verarbeitung
def test_11_upload_ueber_limit_wird_frueh_abgewiesen(client, headers, profile, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    big = b"x" * (2 * 1024 * 1024)
    for hdrs in (headers, {}):  # auch ohne Profil-Header, bevor irgendetwas gespeichert wird
        response = client.post("/imports", data={"import_profile_id": str(profile["id"])},
                               files={"file": ("gross.csv", big, "text/csv")}, headers=hdrs)
        assert response.status_code == 413 and response.json()["error"]["code"] == "file_too_large"


# 12 – Sicherung nicht bei laufendem Worker
def test_12_backup_verweigert_bei_laufendem_worker(tmp_path):
    from app.worker import acquire_lock

    lock = acquire_lock(tmp_path)
    try:
        with pytest.raises(SystemExit):
            acquire_lock(tmp_path)  # zweiter Worker
        result = subprocess.run(
            [str(PROJECT / "scripts/backup.sh"), str(tmp_path / "ziel")],
            env={**os.environ, "IMPORT_DIR": str(tmp_path)}, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0
        assert "Import-Worker läuft" in result.stderr + result.stdout
    finally:
        lock.close()


# 13 – „beliebiges Feld“ verliert die Gegenpartei nicht
def test_13_any_feld_mit_langer_beschreibung(client, headers):
    kat = client.post("/categories", json={"name": "Tanken", "type": "expense"}, headers=headers).json()
    client.post("/mapping-rules", json={"pattern": "ARAL", "target_category_id": kat["id"]}, headers=headers)
    preview = client.post("/mapping-rules/preview",
                          json={"description": "x" * 1000, "counterparty": "ARAL Tankstelle"}, headers=headers).json()
    assert preview["winner"] is not None


# 14 – Abgeglichene manuelle Buchung hat feste Bankfelder
def test_14_abgeglichene_manuelle_buchung_bleibt_fest(client, headers, profile, giro):
    manual = client.post("/transactions", json={"account_id": giro["id"], "booking_date": "2026-01-04",
                                                "amount": "-3.50", "description": "Bäcker"}, headers=headers).json()
    batch = upload(client, headers, profile, csv_file(("05.01.2026", "-3,50", "Brötchen")))
    resolve(client, headers, batch, action="duplicate", decision="ambiguous")
    client.post(f"/imports/{batch['id']}/commit", headers=headers)
    for change in ({"amount": "-4.00"}, {"booking_date": "2026-01-06"}):
        response = client.patch(f"/transactions/{manual['id']}", json=change, headers=headers)
        assert response.json()["error"]["code"] == "imported_fields_fixed"
    assert client.patch(f"/transactions/{manual['id']}", json={"description": "ok"}, headers=headers).status_code == 200


# 15 – Transferpaare mit abgeglichener Seite
def test_15_transferpaar_mit_abgeglichener_seite(client, headers, profile, giro, bank, make_account):
    sparen = make_account("Sparen", type="savings", institution_id=bank["id"], iban=IBAN_B, opening_balance="0")
    pair = client.post("/transfers", json={"from_account_id": giro["id"], "to_account_id": sparen["id"],
                                           "booking_date": "2026-01-10", "amount": "25.00"}, headers=headers).json()
    batch = upload(client, headers, profile, csv_file(("10.01.2026", "25,00", "Umbuchung"), account=IBAN_B))
    assert rows(client, headers, batch, open_only=True)[0]["matched_transaction_id"] == pair["incoming"]["id"]
    resolve(client, headers, batch, action="duplicate", decision="ambiguous")
    client.post(f"/imports/{batch['id']}/commit", headers=headers)

    response = client.delete(f"/transactions/{pair['outgoing']['id']}", headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "transfer_peer_imported"

    total_before = sum(float(_balance(client, headers, a)) for a in (giro["id"], sparen["id"]))
    client.post(f"/transactions/{pair['incoming']['id']}/exclude", json={"reason": "doppelt"}, headers=headers)
    out = client.get(f"/transactions/{pair['outgoing']['id']}", headers=headers).json()
    assert out["excluded_at"] is not None  # beide Seiten gemeinsam
    total_after = sum(float(_balance(client, headers, a)) for a in (giro["id"], sparen["id"]))
    assert total_after == total_before
