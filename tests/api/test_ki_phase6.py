"""KI-Ausbau Phase 6: Monatserklärung (07), Fragen zu Buchungen (08), Erfassung in natürlicher Sprache (21)."""

import json
from datetime import date

import pytest

from app import clock
from app.config import get_settings
from app.services import ai_gateway

HEUTE = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def heute(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: HEUTE)


@pytest.fixture
def ki(monkeypatch):
    """Gefälschte KI mit einer Antwortliste (eine je Anfrage)."""

    class Fake:
        answers: list = []
        calls: list = []

        def __call__(self, messages, schema, **kwargs):
            self.calls.append(messages)
            return json.dumps(self.answers.pop(0))

    fake = Fake()
    fake.answers, fake.calls = [], []
    monkeypatch.setattr(get_settings(), "ai_url", "http://ki.local:11434")
    monkeypatch.setattr(ai_gateway, "complete", fake)
    return fake


@pytest.fixture
def giro(make_account):
    return make_account("Giro", opening_balance="3000.00", opening_balance_date="2025-01-01")


def cat(client, headers, name):
    return next(c for c in client.get("/categories", headers=headers).json() if c["name"] == name)


def tx(client, headers, account, day, amount, counterparty, category=None, description="Buchung"):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount, "description": description,
               "counterparty": counterparty}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def monate(client, headers, giro):
    essen, werkstatt = cat(client, headers, "Lebensmittel"), cat(client, headers, "Werkstatt & Wartung")
    for month in (8, 9, 10, 11):
        tx(client, headers, giro, f"2026-{month:02d}-05", "-300.00", "Supermarkt", essen)
    repair = tx(client, headers, giro, "2026-11-12", "-420.00", "Autohaus Nord", werkstatt, "Reparatur")
    return {"repair": repair, "essen": essen}


# --- 07 Monatserklärung --------------------------------------------------------------------------


def test_monatsvergleich_rechnet_im_backend_und_nennt_einmaleffekte(client, headers, monate):
    result = client.get("/reports/month-comparison", params={"month": "2026-11-01"}, headers=headers).json()
    assert (result["expenses"], result["previous_expenses"], result["delta"]) == ("720.00", "300.00", "420.00")
    assert result["incomplete"] is True  # 20. November: Monat läuft noch
    assert [o["transaction_id"] for o in result["one_offs"]] == [monate["repair"]["id"]]
    top = result["categories"][0]
    assert (top["name"], top["current"], top["previous"]) == ("Mobilität", "420.00", "0.00")


def test_ki_erklaerung_nur_mit_gelieferten_belegen(client, headers, monate, ki):
    ki.answers = [{"text": "Die Ausgaben liegen 420 € über dem Vormonat, vor allem wegen einer Reparatur.",
                   "verweise": [monate["repair"]["id"], 999999]}]
    result = client.post("/reports/month-comparison/explain", params={"month": "2026-11-01"}, headers=headers).json()
    assert "Reparatur" in result["text"] and result["references"] == [monate["repair"]["id"]]
    data = ki.calls[0][1]["content"]
    assert "420.00" in data and ai_gateway.DATA_START in data


def test_erklaerung_ohne_ki_meldet_nicht_verfuegbar(client, headers, monate, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_url", None)
    response = client.post("/reports/month-comparison/explain", params={"month": "2026-11-01"}, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "ai_unavailable"


# --- 08 Fragen zu Buchungen ----------------------------------------------------------------------


def test_frage_wird_ueber_erlaubtes_werkzeug_beantwortet(client, headers, monate, ki):
    ki.answers = [
        {"werkzeug": "transactions_search", "date_from": "2026-01-01", "date_to": "2026-11-20", "suche": "Supermarkt",
         "kategorie_id": None, "typ": None, "monate": None, "gruppierung": None},
        {"antwort": "Dieses Jahr gingen 1.200,00 € an den Supermarkt.", "belege": []},
    ]
    response = client.post("/ask", json={"question": "Wie viel ging dieses Jahr an den Supermarkt?"}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["tool"] == "transactions_search" and result["result"]["sum"] == "-1200.00"
    assert result["result"]["count"] == 4
    assert (result["period"]["from"], result["period"]["to"]) == ("2026-01-01", "2026-11-20")
    assert result["data_as_of"] == "2026-11-20" and "1.200" in result["answer"]


def test_unzulaessige_parameter_werden_nicht_ausgefuehrt(client, headers, monate, ki, other_user):
    fremd = next(c for c in client.get("/categories", headers=other_user["headers"]).json())
    ki.answers = [{"werkzeug": "report_categories", "date_from": "2026-11-01", "date_to": "2026-11-30", "suche": None,
                   "kategorie_id": fremd["id"], "typ": "expense", "monate": None, "gruppierung": None}]
    response = client.post("/ask", json={"question": "Zeig mir fremde Kategorie"}, headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "ask_invalid_parameters"
    assert len(ki.calls) == 1  # keine zweite Anfrage, nichts ausgeführt


# --- 21 Erfassung in natürlicher Sprache ---------------------------------------------------------


def test_beschreibung_wird_zum_entwurf_ohne_erfundenes_konto(client, headers, giro, make_account, ki):
    make_account("Bargeld", type="cash", opening_balance="50.00")
    essen = cat(client, headers, "Restaurant & Café")
    ki.answers = [{"betrag": "18.50", "richtung": "ausgabe", "datum": None, "datum_relativ": "gestern",
                   "kategorie_id": essen["id"], "konto_id": 987654, "beschreibung": "Mittagessen"}]
    draft = client.post("/entries/parse", json={"text": "Gestern 18,50 € bar für Mittagessen"}, headers=headers).json()
    assert (draft["amount"], draft["booking_date"], draft["category_id"]) == ("-18.50", "2026-11-19", essen["id"])
    assert draft["account_id"] is None and "account" in draft["questions"]
    assert draft["description"] == "Mittagessen"


def test_moegliche_vorhandene_buchung_wird_angezeigt(client, headers, giro, ki):
    existing = tx(client, headers, giro, "2026-11-19", "-18.50", "Bistro")
    ki.answers = [{"betrag": "18.50", "richtung": "ausgabe", "datum": "2026-11-18", "datum_relativ": None,
                   "kategorie_id": None, "konto_id": giro["id"], "beschreibung": "Mittagessen"}]
    draft = client.post("/entries/parse", json={"text": "18,50 Mittagessen am 18.11."}, headers=headers).json()
    assert draft["possible_duplicate"]["id"] == existing["id"] and draft["account_id"] == giro["id"]


def test_ohne_ki_erkennt_die_regel_betrag_und_datum(client, headers, giro, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_url", None)
    draft = client.post("/entries/parse", json={"text": "heute 4,20 € Bäcker"}, headers=headers).json()
    assert (draft["amount"], draft["booking_date"], draft["ai_used"]) == ("-4.20", "2026-11-20", False)
