"""Regeln und Prüfliste: Reihenfolge, Regex mit Zeitlimit, manuelle Kategorien bleiben, Bestätigen."""

import pytest

from app.models import Transaction


@pytest.fixture
def giro(make_account):
    return make_account("Giro")


def _cat(client, headers, name, type_="expense"):
    response = client.post("/categories", json={"name": name, "type": type_}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _rule(client, headers, pattern, category, **extra):
    response = client.post(
        "/mapping-rules", json={"pattern": pattern, "target_category_id": category["id"], **extra}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _imported(client, headers, session, giro, description, amount="-10.00", counterparty=None, day="2026-02-01"):
    """Buchung wie aus einem Import: ohne Kategorie, Quelle import."""
    tx = client.post(
        "/transactions",
        json={"account_id": giro["id"], "booking_date": day, "amount": amount,
              "description": description, "counterparty": counterparty},
        headers=headers,
    ).json()
    session.get(Transaction, tx["id"]).source = "import"
    session.commit()
    return tx


def _preview(client, headers, **payload):
    return client.post("/mapping-rules/preview", json=payload, headers=headers).json()


def test_reihenfolge_prioritaet_dann_id(client, headers):
    lebensmittel = _cat(client, headers, "Lebensmittel-Test")
    drogerie = _cat(client, headers, "Drogerie-Test")
    r1 = _rule(client, headers, "rewe", lebensmittel)
    r2 = _rule(client, headers, "REWE Markt", drogerie)  # gleiche Priorität, jünger
    preview = _preview(client, headers, description="Einkauf REWE Markt GmbH")
    assert [r["id"] for r in preview["matching"]] == [r1["id"], r2["id"]]
    assert preview["winner"]["id"] == r1["id"]

    client.patch(f"/mapping-rules/{r2['id']}", json={"priority": 10}, headers=headers)
    assert _preview(client, headers, description="REWE Markt")["winner"]["id"] == r2["id"]
    assert [r["id"] for r in client.get("/mapping-rules", headers=headers).json()] == [r2["id"], r1["id"]]


def test_feld_und_gross_kleinschreibung(client, headers):
    kat = _cat(client, headers, "Test")
    _rule(client, headers, "Amazon", kat, match_field="counterparty", case_sensitive=True)
    assert _preview(client, headers, description="Amazon Bestellung")["winner"] is None
    assert _preview(client, headers, counterparty="amazon EU")["winner"] is None
    assert _preview(client, headers, counterparty="Amazon EU")["winner"] is not None


def test_regex_und_zeitlimit(client, headers):
    kat = _cat(client, headers, "Abo")
    response = client.post("/mapping-rules", json={"pattern": "netflix(", "match_type": "regex",
                                                   "target_category_id": kat["id"]}, headers=headers)
    assert response.json()["error"]["code"] == "invalid_regex"
    _rule(client, headers, r"^(netflix|spotify)\b", kat, match_type="regex")
    assert _preview(client, headers, description="SPOTIFY AB Stockholm")["winner"] is not None
    # Extrem langsames Muster: Zeitlimit greift, gilt als kein Treffer statt den Server zu blockieren
    slow = _rule(client, headers, r"(x+x+)+y", kat, match_type="regex", priority=1)
    preview = _preview(client, headers, description="x" * 900)
    assert slow["id"] not in [r["id"] for r in preview["matching"]]


def test_zielkategorie_muss_eigen_und_aktiv_sein(client, headers, other_user):
    fremd = _cat(client, other_user["headers"], "Fremd")
    response = client.post("/mapping-rules", json={"pattern": "abc", "target_category_id": fremd["id"]}, headers=headers)
    assert response.status_code == 404
    kat = _cat(client, headers, "Inaktiv")
    client.patch(f"/categories/{kat['id']}", json={"active": False}, headers=headers)
    response = client.post("/mapping-rules", json={"pattern": "abc", "target_category_id": kat["id"]}, headers=headers)
    assert response.json()["error"]["code"] == "category_inactive"


def test_import_wird_per_regel_kategorisiert(client, headers, make_institution, make_account):
    from tests.api.test_imports import COLUMN_MAP, IBAN_A, csv_file, upload

    bank = make_institution("Sparkasse")
    giro = make_account("Giro", institution_id=bank["id"], iban=IBAN_A)
    profile = client.post("/import-profiles", json={"name": "P", "institution_id": bank["id"], "format": "csv",
                                                    "column_map": COLUMN_MAP}, headers=headers).json()
    kat = _cat(client, headers, "Tanken")
    rule = _rule(client, headers, "aral", kat)
    upload(client, headers, profile, csv_file(("02.01.2026", "-50,00", "Kartenzahlung", "ARAL Tankstelle"),
                                              ("03.01.2026", "-5,00", "Unbekannt", "Irgendwer")))
    txs = {t["counterparty"]: t for t in client.get("/transactions", headers=headers).json()["items"]}
    aral = txs["ARAL Tankstelle"]
    assert (aral["category_id"], aral["review_status"], aral["category_source"], aral["applied_rule_id"]) == (
        kat["id"], "auto_categorized", "rule", rule["id"],
    )
    assert txs["Irgendwer"]["review_status"] == "needs_review"
    assert giro["id"] == aral["account_id"]


def test_rueckwirkend_anwenden_vorschau_und_manuelle_bleiben(client, headers, session, giro):
    kat = _cat(client, headers, "Supermarkt")
    manuell = _cat(client, headers, "Manuell")
    offen = _imported(client, headers, session, giro, "EDEKA Center")
    fest = _imported(client, headers, session, giro, "EDEKA Tankstelle")
    client.patch(f"/transactions/{fest['id']}", json={"category_id": manuell["id"]}, headers=headers)
    _imported(client, headers, session, giro, "Kiosk")
    _rule(client, headers, "edeka", kat)

    preview = client.post("/mapping-rules/apply", headers=headers).json()
    assert preview["dry_run"] is True and preview["affected"] == 1
    assert preview["sample"][0]["transaction_id"] == offen["id"]
    assert client.get(f"/transactions/{offen['id']}", headers=headers).json()["category_id"] is None

    result = client.post("/mapping-rules/apply", params={"dry_run": False}, headers=headers).json()
    assert result["affected"] == 1
    assert client.get(f"/transactions/{offen['id']}", headers=headers).json()["category_id"] == kat["id"]
    assert client.get(f"/transactions/{fest['id']}", headers=headers).json()["category_id"] == manuell["id"]
    # Erneut anwenden ändert nichts mehr
    assert client.post("/mapping-rules/apply", headers=headers).json()["affected"] == 0


def test_regel_auf_deaktivierte_kategorie_greift_nicht(client, headers, session, giro):
    kat = _cat(client, headers, "Alt")
    _rule(client, headers, "lidl", kat)
    client.patch(f"/categories/{kat['id']}", json={"active": False}, headers=headers)
    _imported(client, headers, session, giro, "LIDL sagt danke")
    assert client.post("/mapping-rules/apply", headers=headers).json()["affected"] == 0


def test_kategorie_mit_regel_nicht_loeschbar_merge_haengt_um(client, headers):
    quelle = _cat(client, headers, "Quelle")
    ziel = _cat(client, headers, "Ziel")
    rule = _rule(client, headers, "abc", quelle)
    response = client.delete(f"/categories/{quelle['id']}", headers=headers)
    assert response.json()["error"]["details"] == {"rules": 1}
    client.post(f"/categories/{quelle['id']}/merge", json={"target_id": ziel["id"]}, headers=headers)
    assert client.get(f"/mapping-rules/{rule['id']}", headers=headers).json()["target_category_id"] == ziel["id"]


# --- Prüfliste -----------------------------------------------------------------


def test_pruefliste_bestaetigen(client, headers, session, giro):
    kat = _cat(client, headers, "Supermarkt")
    _rule(client, headers, "edeka", kat)
    auto = _imported(client, headers, session, giro, "EDEKA")
    offen = _imported(client, headers, session, giro, "Unbekannt")
    client.post("/mapping-rules/apply", params={"dry_run": False}, headers=headers)

    page = client.get("/review", headers=headers).json()
    assert page["total"] == 2
    assert {i["transaction"]["review_status"] for i in page["items"]} == {"auto_categorized", "needs_review"}

    # Ohne Kategorie nicht bestätigbar
    response = client.post(f"/review/{offen['id']}/confirm", json={}, headers=headers)
    assert response.json()["error"]["code"] == "category_required"
    # Automatisch kategorisierte bestätigen: Herkunft „Regel“ bleibt erhalten
    tx = client.post(f"/review/{auto['id']}/confirm", json={}, headers=headers).json()
    assert (tx["review_status"], tx["category_source"]) == ("confirmed", "rule")
    # Als Umbuchung bestätigen
    tx = client.post(f"/review/{offen['id']}/confirm", json={"as_transfer": True}, headers=headers).json()
    assert (tx["kind"], tx["category_id"], tx["review_status"]) == ("transfer", None, "confirmed")
    assert client.get("/review", headers=headers).json()["total"] == 0


def test_sammelbestaetigung_alles_oder_nichts(client, headers, session, giro, other_user, make_account):
    kat = _cat(client, headers, "Sammel")
    a = _imported(client, headers, session, giro, "A")
    b = _imported(client, headers, session, giro, "B")
    fremdes_konto = make_account("Fremd", hdrs=other_user["headers"])
    fremd = client.post("/transactions", json={"account_id": fremdes_konto["id"], "booking_date": "2026-02-01",
                                               "amount": "-1.00", "description": "x"},
                        headers=other_user["headers"]).json()
    response = client.post("/review/bulk-confirm",
                           json={"transaction_ids": [a["id"], b["id"], fremd["id"]], "category_id": kat["id"]},
                           headers=headers)
    assert response.status_code == 404
    assert client.get(f"/transactions/{a['id']}", headers=headers).json()["review_status"] == "needs_review"

    response = client.post("/review/bulk-confirm", json={"transaction_ids": [a["id"], b["id"]], "category_id": kat["id"]},
                           headers=headers)
    assert response.json() == {"confirmed": 2}
    tx = client.get(f"/transactions/{a['id']}", headers=headers).json()
    assert (tx["category_id"], tx["category_source"], tx["review_status"]) == (kat["id"], "manual", "confirmed")


def test_regelvorschlag_ohne_ziffern_und_referenzen(client, headers, session, giro):
    kat = _cat(client, headers, "Online")
    tx = _imported(client, headers, session, giro, "AMAZON PAYMENTS 302-1234567-8901234 EREF+ABC123 12.01.2026",
                   counterparty=None)
    _imported(client, headers, session, giro, "Amazon Payments Bestellung 999")
    client.patch(f"/transactions/{tx['id']}", json={"category_id": kat["id"]}, headers=headers)
    suggestion = client.post(f"/review/{tx['id']}/suggest-rule", headers=headers).json()
    assert suggestion["pattern"] == "AMAZON PAYMENTS"
    assert suggestion["match_field"] == "description"
    assert suggestion["target_category_id"] == kat["id"]
    assert suggestion["matching_transactions"] == 1  # nur die noch offene; manuelle bleibt unberührt
    assert client.get("/mapping-rules", headers=headers).json() == []  # nichts gespeichert


def test_pruefliste_zeigt_vorgeschlagene_kreditrate(client, headers, make_institution, make_account):
    from tests.api.test_imports import COLUMN_MAP, IBAN_A, LENDER_IBAN, csv_file, upload

    bank = make_institution("Sparkasse")
    giro = make_account("Giro", institution_id=bank["id"], iban=IBAN_A, opening_balance="5000.00")
    profile = client.post("/import-profiles", json={"name": "P", "institution_id": bank["id"], "format": "csv",
                                                    "column_map": COLUMN_MAP}, headers=headers).json()
    loan = client.post("/loans", json={"name": "Kredit", "loan_type": "annuity", "lender_name": "Autobank",
                                       "lender_iban": LENDER_IBAN, "annual_interest_rate": "5",
                                       "current_balance": "10000.00", "balance_date": "2026-01-01",
                                       "first_due_date": "2026-01-30", "term_months": 48,
                                       "payment_account_id": giro["id"]}, headers=headers).json()
    upload(client, headers, profile, csv_file(("31.01.2026", "-231,00", "Rate", "Autobank", LENDER_IBAN)))
    item = client.get("/review", headers=headers).json()["items"][0]
    assert item["suggested_loan"]["loan_id"] == loan["id"] and item["suggested_loan"]["seq"] == 1
    client.post(f"/loans/{loan['id']}/payments", json={"transaction_id": item["transaction"]["id"]}, headers=headers)
    assert client.get("/review", headers=headers).json()["total"] == 0
