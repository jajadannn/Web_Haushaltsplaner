"""KI-Ausbau Phase 7: Umbuchungen/Erstattungen (06), Split-Vorlagen (13), Belege (14), Vertragsdaten (15)."""

import io
import json
from datetime import date

import pytest
from pypdf import PdfWriter

from app import clock
from app.config import get_settings
from app.services import ai_gateway, ai_jobs

HEUTE = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def heute(monkeypatch, tmp_path):
    monkeypatch.setattr(clock, "today", lambda: HEUTE)
    monkeypatch.setattr(get_settings(), "document_dir", tmp_path / "documents")


@pytest.fixture
def ki(monkeypatch):
    class Fake:
        answer: dict = {}
        calls: list = []

        def __call__(self, messages, schema, **kwargs):
            self.calls.append(messages)
            return json.dumps(self.answer)

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr(get_settings(), "ai_url", "http://ki.local:11434")
    monkeypatch.setattr(ai_gateway, "complete", fake)
    return fake


@pytest.fixture
def giro(make_account):
    return make_account("Giro", iban="DE89370400440532013000", opening_balance="2000.00",
                        opening_balance_date="2025-01-01")


@pytest.fixture
def tagesgeld(make_account):
    return make_account("Tagesgeld", type="savings", iban="DE02120300000000202051", opening_balance="0",
                        opening_balance_date="2025-01-01")


def cat(client, headers, name):
    return next(c for c in client.get("/categories", headers=headers).json() if c["name"] == name)


def tx(client, headers, account, day, amount, counterparty=None, category=None, description="Buchung", **extra):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount, "description": description,
               "counterparty": counterparty, **extra}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def found(client, headers, kind):
    client.post("/suggestions/refresh", headers=headers)
    return client.get("/suggestions", params={"kind": kind}, headers=headers).json()


# --- 06 Umbuchungen und Erstattungen -------------------------------------------------------------


def test_zwei_gegenbuchungen_zwischen_eigenen_konten_werden_als_umbuchung_vorgeschlagen(
    client, headers, giro, tagesgeld
):
    out = tx(client, headers, giro, "2026-11-10", "-500.00", "Tagesgeld", counterparty_iban="DE02120300000000202051")
    inc = tx(client, headers, tagesgeld, "2026-11-11", "500.00", "Giro", counterparty_iban="DE89370400440532013000")
    tx(client, headers, giro, "2026-11-12", "-500.00", "Fremde GmbH")  # gleicher Betrag, aber fremd
    matches = found(client, headers, "transfer_match")
    assert len(matches) == 1 and set(matches[0]["payload"]["transaction_ids"]) == {out["id"], inc["id"]}
    client.post(f"/suggestions/{matches[0]['id']}/accept", json={}, headers=headers)
    a = client.get(f"/transactions/{out['id']}", headers=headers).json()
    b = client.get(f"/transactions/{inc['id']}", headers=headers).json()
    assert (a["kind"], b["kind"], a["transfer_peer_id"], b["transfer_peer_id"]) == ("transfer", "transfer", inc["id"],
                                                                                    out["id"])


def test_erstattung_wird_dem_einkauf_zugeordnet(client, headers, giro):
    kleidung = cat(client, headers, "Kleidung & Schuhe")
    kauf = tx(client, headers, giro, "2026-10-12", "-79.90", "Modehaus Nord", kleidung)
    gutschrift = tx(client, headers, giro, "2026-10-20", "29.90", "Modehaus Nord", description="Rückerstattung")
    matches = found(client, headers, "refund_match")
    assert len(matches) == 1
    assert (matches[0]["payload"]["refund_id"], matches[0]["payload"]["original_id"]) == (gutschrift["id"], kauf["id"])
    assert matches[0]["payload"]["partial"] is True
    client.post(f"/suggestions/{matches[0]['id']}/accept", json={}, headers=headers)
    got = client.get(f"/transactions/{gutschrift['id']}", headers=headers).json()
    assert got["category_id"] == kleidung["id"] and got["review_status"] == "confirmed"
    assert [s["status"] for s in found(client, headers, "refund_match")] == ["accepted"]  # nicht doppelt


# --- 13 Split-Vorlagen ---------------------------------------------------------------------------


def test_wiederkehrende_aufteilung_wird_fuer_neue_buchung_vorgeschlagen(client, headers, giro):
    mobil, internet = cat(client, headers, "Mobilfunk"), cat(client, headers, "Internet & Festnetz")
    for month in (9, 10):
        tx(client, headers, giro, f"2026-{month:02d}-03", "-59.98", "Kombi-Anbieter",
           splits=[{"amount": "-19.99", "category_id": mobil["id"]}, {"amount": "-39.99", "category_id": internet["id"]}])
    neu = tx(client, headers, giro, "2026-11-03", "-59.98", "Kombi-Anbieter")
    matches = found(client, headers, "split_template")
    assert len(matches) == 1 and matches[0]["payload"]["transaction_id"] == neu["id"]
    client.post(f"/suggestions/{matches[0]['id']}/accept", json={}, headers=headers)
    got = client.get(f"/transactions/{neu['id']}", headers=headers).json()
    assert sorted((s["amount"], s["category_id"]) for s in got["splits"]) == sorted(
        [("-19.99", mobil["id"]), ("-39.99", internet["id"])])


def test_abweichender_gesamtbetrag_bekommt_keine_feste_vorlage(client, headers, giro):
    mobil, internet = cat(client, headers, "Mobilfunk"), cat(client, headers, "Internet & Festnetz")
    for month in (9, 10):
        tx(client, headers, giro, f"2026-{month:02d}-03", "-59.98", "Kombi-Anbieter",
           splits=[{"amount": "-19.99", "category_id": mobil["id"]}, {"amount": "-39.99", "category_id": internet["id"]}])
    tx(client, headers, giro, "2026-11-03", "-12.00", "Kombi-Anbieter")
    assert found(client, headers, "split_template") == []


# --- 14 Belege und 15 Vertragsdaten --------------------------------------------------------------


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def upload_doc(client, headers, content, name="beleg.png", mime="image/png", kind="receipt"):
    response = client.post("/documents", data={"kind": kind}, files={"file": (name, content, mime)}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_beleg_wird_ausgelesen_und_der_passenden_buchung_vorgeschlagen(client, headers, session, giro, ki):
    kauf = tx(client, headers, giro, "2026-11-14", "-45.60", "Baumarkt Süd")
    doc = upload_doc(client, headers, PNG)
    assert doc["status"] == "pending"
    ki.answer = {"art": "beleg", "haendler": "Baumarkt Süd", "datum": "2026-11-14", "betrag": "45.60",
                 "waehrung": "EUR", "positionen": [{"text": "Schrauben", "betrag": "5.60"},
                                                   {"text": "Farbe", "betrag": "40.00"}],
                 "vertrag": None, "fundstellen": []}
    assert ai_jobs.run_pending(session) == 1
    got = client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert got["status"] == "extracted" and got["extracted"]["betrag"] == "45.60"
    matches = client.get("/suggestions", params={"kind": "receipt_match"}, headers=headers).json()
    assert len(matches) == 1 and matches[0]["payload"]["transaction_id"] == kauf["id"]
    client.post(f"/suggestions/{matches[0]['id']}/accept", json={}, headers=headers)
    assert [link["transaction_id"] for link in client.get(f"/documents/{doc['id']}", headers=headers).json()["links"]] \
        == [kauf["id"]]
    assert client.get(f"/documents/{doc['id']}/file", headers=headers).content == PNG


def test_vertragsdaten_nur_mit_fundstelle(client, headers, session, giro, ki):
    upload_doc(client, headers, PNG, name="police.png", kind="contract")
    ki.answer = {"art": "vertrag", "haendler": "Hausrat AG", "datum": "2026-10-01", "betrag": "90.00", "waehrung": "EUR",
                 "positionen": [],
                 "vertrag": {"anbieter": "Hausrat AG", "beitrag": "90.00", "rhythmus_monate": 3,
                             "naechste_faelligkeit": "2027-01-15", "kuendigungsfrist": "3 Monate zum Ablauf",
                             "laufzeit_ende": "2027-09-30"},
                 "fundstellen": [{"feld": "beitrag", "seite": 1, "zitat": "Beitrag 90,00 EUR vierteljährlich"},
                                 {"feld": "rhythmus_monate", "seite": 1, "zitat": "vierteljährlich"},
                                 {"feld": "naechste_faelligkeit", "seite": 1, "zitat": "fällig am 15.01.2027"},
                                 {"feld": "kuendigungsfrist", "seite": 2, "zitat": "Kündigung 3 Monate zum Ablauf"}]}
    ai_jobs.run_pending(session)
    drafts = client.get("/suggestions", params={"kind": "contract_draft"}, headers=headers).json()
    assert len(drafts) == 1
    contract = drafts[0]["payload"]["contract"]
    assert contract["laufzeit_ende"] is None  # ohne Fundstelle verworfen
    assert contract["kuendigungsfrist"] == "3 Monate zum Ablauf"
    accepted = client.post(f"/suggestions/{drafts[0]['id']}/accept", json={}, headers=headers).json()
    fc = client.get(f"/fixed-costs/{accepted['result_id']}", headers=headers).json()
    assert (fc["name"], fc["amount"], fc["interval_months"], fc["first_due_date"]) == (
        "Hausrat AG", "90.00", 3, "2027-01-15")
    merchants = client.get("/merchants", headers=headers).json()
    contracts = client.get(f"/merchants/{merchants[0]['id']}/contracts", headers=headers).json()
    assert contracts[0]["notice_period"] == "3 Monate zum Ablauf" and contracts[0]["fixed_cost_id"] == fc["id"]


def test_pdf_ohne_textebene_wird_mit_hinweis_abgelehnt(client, headers, session, ki):
    doc = upload_doc(client, headers, blank_pdf(), name="scan.pdf", mime="application/pdf")
    ai_jobs.run_pending(session)
    got = client.get(f"/documents/{doc['id']}", headers=headers).json()
    assert got["status"] == "failed" and "Textebene" in got["error"]


def test_dokumente_sind_profilgetrennt_und_nur_erlaubte_dateitypen(client, headers, other_user):
    doc = upload_doc(client, headers, PNG)
    assert client.get(f"/documents/{doc['id']}", headers=other_user["headers"]).status_code == 404
    response = client.post("/documents", data={"kind": "receipt"},
                           files={"file": ("x.exe", b"MZ...", "application/octet-stream")}, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "document_type"
