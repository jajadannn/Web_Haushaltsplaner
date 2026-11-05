"""KI-Ausbau Phase 4: Importassistent (11), Importdiagnose (12), Konsistenz (19), gezielte Rückfragen (20)."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app import clock
from app.config import get_settings
from app.importers.csv_profile import CsvOptions, parse_csv
from app.importers.detect import detect_csv
from app.services import ai_gateway
from tests.api.test_imports import upload
from tests.fixtures.imports.catalog import FIXTURE_DIR, FIXTURES

CSV_FIXTURES = [name for name, fx in FIXTURES.items() if fx["format"] == "csv"]


@pytest.fixture(autouse=True)
def heute(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 11, 20))


# --- 11 Erkennung des CSV-Aufbaus ----------------------------------------------------------------


@pytest.mark.parametrize("name", CSV_FIXTURES)
def test_erkennung_liest_jede_beispieldatei_wie_das_handgeschriebene_profil(name):
    content = (FIXTURE_DIR / name).read_bytes()
    expected = FIXTURES[name]["expected"]
    detection = detect_csv(content)
    result = parse_csv(content, CsvOptions(**detection.options))
    assert len(result.rows) == expected["rows"]
    assert str(sum((r.amount for r in result.rows), Decimal("0"))) == expected["sum"]
    assert len(result.errors) == expected["errors"]
    assert result.pending_skipped == expected.get("pending_skipped", 0)
    assert detection.safe == (expected["errors"] == 0)


def test_entwurf_endpunkt_liefert_profil_und_vorschau(client, headers):
    content = (FIXTURE_DIR / "debit_credit.csv").read_bytes()
    response = client.post("/import-profiles/draft", files={"file": ("umsatz.csv", content, "text/csv")},
                           headers=headers)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["options"]["sign_mode"] == "debit_credit_columns" and draft["safe"] is True
    assert len(draft["preview"]) == 8 and draft["preview"][0]["booking_date"] == "2026-01-05"


def test_vorschau_mit_angepasstem_profil_meldet_zeilenfehler(client, headers):
    content = (FIXTURE_DIR / "generic_signed.csv").read_bytes()
    draft = client.post("/import-profiles/draft", files={"file": ("a.csv", content, "text/csv")},
                        headers=headers).json()
    options = draft["options"] | {"date_format": "%Y-%m-%d"}
    response = client.post("/import-profiles/preview", data={"settings": json.dumps(options)},
                           files={"file": ("a.csv", content, "text/csv")}, headers=headers)
    assert response.status_code == 200
    assert response.json()["safe"] is False and response.json()["errors"]


def test_ki_ordnet_nur_unklare_spalten_aus_der_festen_liste_zu(client, headers, monkeypatch):
    content = "Tag;Wert;Partner;Notiz\n02.01.2026;-10,00;Bäcker;Brötchen\n03.01.2026;-5,50;Kiosk;Zeitung\n".encode()
    monkeypatch.setattr(get_settings(), "ai_url", "http://ki.local:11434")
    answer = {"zuordnung": [{"spalte": "Tag", "rolle": "booking_date"}, {"spalte": "Wert", "rolle": "amount"},
                            {"spalte": "Partner", "rolle": "counterparty"}, {"spalte": "Notiz", "rolle": "description"}]}
    monkeypatch.setattr(ai_gateway, "complete", lambda messages, schema, **kw: json.dumps(answer))
    draft = client.post("/import-profiles/draft", params={"ai": True},
                        files={"file": ("x.csv", content, "text/csv")}, headers=headers).json()
    assert draft["ai_used"] is True and draft["safe"] is True
    assert draft["options"]["column_map"]["booking_date"] == "Tag" and draft["rows_parsed"] == 2


# --- 12 Importdiagnose ---------------------------------------------------------------------------


@pytest.fixture
def bank(make_institution):
    return make_institution("Sparkasse")


def test_diagnose_erklaert_falsches_datumsformat_und_schlaegt_korrektur_vor(client, headers, bank, make_account):
    make_account("Giro", institution_id=bank["id"], iban="DE89370400440532013000", opening_balance_date="2025-01-01")
    content = (FIXTURE_DIR / "generic_signed.csv").read_bytes()
    options = FIXTURES["generic_signed.csv"]["options"] | {"date_format": "%Y-%m-%d"}
    profile = client.post("/import-profiles", json={"name": "Falsch", "institution_id": bank["id"], "format": "csv",
                                                    **options}, headers=headers).json()
    batch = upload(client, headers, profile, content)
    assert batch["status"] == "failed"
    diagnosis = client.get(f"/imports/{batch['id']}/diagnosis", headers=headers).json()
    assert diagnosis["items"][0]["code"] == "row_errors"
    assert "Datum" in diagnosis["items"][0]["explanation"]
    fix = diagnosis["fix"]
    assert fix["changes"] == {"date_format": "%d.%m.%Y"}
    accepted = client.post(f"/suggestions/{fix['suggestion_id']}/accept", json={}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert client.get(f"/import-profiles/{profile['id']}", headers=headers).json()["date_format"] == "%d.%m.%Y"
    retried = client.post(f"/imports/{batch['id']}/retry", headers=headers)
    assert retried.status_code == 200


# --- 19 Konsistenz und 20 Rückfragen ---------------------------------------------------------------


def cat(client, headers, name):
    return next(c for c in client.get("/categories", headers=headers).json() if c["name"] == name)


def tx(client, headers, account, day, amount, counterparty, category=None, description="Lastschrift"):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount, "description": description,
               "counterparty": counterparty}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_widerspruechliche_bestaetigungen_werden_gemeldet(client, headers, make_account):
    giro = make_account("Giro", opening_balance_date="2025-01-01")
    mobil, internet = cat(client, headers, "Mobilfunk"), cat(client, headers, "Internet & Festnetz")
    for day in ("2026-09-02", "2026-10-02"):
        tx(client, headers, giro, day, "-29.99", "Telekom Deutschland", mobil)
    tx(client, headers, giro, "2026-11-02", "-29.99", "Telekom Deutschland", internet)
    client.post("/suggestions/refresh", headers=headers)
    found = client.get("/suggestions", params={"kind": "consistency"}, headers=headers).json()
    assert len(found) == 1 and found[0]["payload"]["type"] == "mixed_categories"
    assert set(found[0]["payload"]["category_ids"]) == {mobil["id"], internet["id"]}
    # Übernehmen = als gewollt markieren; es wird nichts geändert und nicht erneut gemeldet
    client.post(f"/suggestions/{found[0]['id']}/accept", json={}, headers=headers)
    client.post("/suggestions/refresh", headers=headers)
    assert [s["status"] for s in client.get("/suggestions", params={"kind": "consistency"},
                                            headers=headers).json()] == ["accepted"]


def test_rueckfrage_zu_zwei_referenzen_speichert_die_antwort_als_vertraege(client, headers, make_account):
    giro = make_account("Giro", opening_balance_date="2025-01-01")
    merchant = client.post("/merchants", json={"name": "Funkfix"}, headers=headers).json()
    client.post(f"/merchants/{merchant['id']}/aliases", json={"match_type": "name", "value": "Funkfix GmbH"},
                headers=headers)
    for month in (8, 9, 10, 11):
        tx(client, headers, giro, f"2026-{month:02d}-03", "-19.99", "Funkfix GmbH", description=f"Vertrag K-100 {month}")
        tx(client, headers, giro, f"2026-{month:02d}-04", "-24.99", "Funkfix GmbH", description=f"Vertrag K-200 {month}")
    client.post("/suggestions/refresh", headers=headers)
    questions = client.get("/suggestions", params={"kind": "question"}, headers=headers).json()
    assert len(questions) == 1
    q = questions[0]
    assert set(q["payload"]["references"]) == {"K-100", "K-200"}
    assert [o["value"] for o in q["payload"]["options"]] == ["separate", "same"]
    response = client.post(f"/suggestions/{q['id']}/accept", json={"answer": "separate"}, headers=headers)
    assert response.status_code == 200, response.text
    contracts = client.get(f"/merchants/{merchant['id']}/contracts", headers=headers).json()
    assert sorted(c["reference"] for c in contracts) == ["K-100", "K-200"]
