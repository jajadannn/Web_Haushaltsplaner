"""Fixkosten, Monats-Spielraum und Wanddisplay – mit handgerechnetem Monatsszenario."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import clock
from app.db import get_session
from app.main import app

STICHTAG = date(2026, 11, 18)


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: STICHTAG)
    return STICHTAG


def _cat(client, headers, name, type_="expense"):
    response = client.post("/categories", json={"name": name, "type": type_}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _tx(client, headers, account, day, amount, category=None, **extra):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount,
               "description": extra.pop("description", "Buchung"), **extra}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _fixed(client, headers, **payload):
    response = client.post("/fixed-costs", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def szenario(client, headers, make_account, today):
    giro = make_account("Giro", opening_balance="1000.00", opening_balance_date="2026-01-01")
    tagesgeld = make_account("Tagesgeld", type="savings", opening_balance="0", opening_balance_date="2026-01-01")
    gehalt = _cat(client, headers, "Gehalt-Test", "income")
    miete = _cat(client, headers, "Miete-Test")
    essen = _cat(client, headers, "Essen-Test")
    _fixed(client, headers, name="Miete", amount="850.00", due_day=1, category_id=miete["id"])
    _fixed(client, headers, name="Strom", amount="90.00", due_day=15, match_text="Stadtwerke")
    _fixed(client, headers, name="Handy", amount="24.99", due_day=20, match_text="Telekom")
    loan = client.post("/loans", json={
        "name": "Autokredit", "loan_type": "annuity", "lender_name": "Autobank", "annual_interest_rate": "5",
        "current_balance": "10000.00", "balance_date": "2026-11-01", "first_due_date": "2026-11-30",
        "term_months": 48, "payment_account_id": giro["id"]}, headers=headers).json()

    _tx(client, headers, giro, "2026-11-01", "-850.00", miete, description="Miete November")
    _tx(client, headers, giro, "2026-11-02", "3000.00", gehalt, description="Gehalt")
    _tx(client, headers, giro, "2026-11-10", "-45.50", essen)
    _tx(client, headers, giro, "2026-11-12", "10.00", essen, description="Pfand")  # Erstattung
    _tx(client, headers, giro, "2026-11-14", "-90.00", counterparty="Stadtwerke Musterstadt")
    _tx(client, headers, giro, "2026-11-16", "-20.00", description="Kiosk")  # unkategorisiert
    _tx(client, headers, giro, "2026-11-17", "50.00", description="Rückzahlung Freund")  # ungeklärt
    _tx(client, headers, giro, "2026-10-30", "-999.00", essen)  # Vormonat
    client.post("/transfers", json={"from_account_id": giro["id"], "to_account_id": tagesgeld["id"],
                                    "booking_date": "2026-11-05", "amount": "100.00"}, headers=headers)
    return {"giro": giro, "loan": loan, "essen": essen, "miete": miete}


def test_monats_spielraum_handgerechnet(client, headers, szenario):
    r = client.get("/budget/month", headers=headers).json()
    # Einnahmen 3000; Fixkosten 850 + 90 + 24,99 + Kreditrate 230,30 = 1195,29
    # Ausgaben 850 + (45,50 − 10) + 90 + 20 = 995,50; davon Fixkosten bezahlt 850 + 90 → variabel 55,50
    # Frei verfügbar 3000 − 1195,29 − 55,50 = 1749,21; 13 Tage übrig (18.–30.11.) → 134,55 pro Tag
    assert (r["month"], r["income"], r["uncategorized_in"]) == ("2026-11-01", "3000.00", "50.00")
    assert (r["fixed_total"], r["fixed_paid"], r["variable_spent"]) == ("1195.29", "940.00", "55.50")
    assert (r["available"], r["days_left"], r["available_per_day"]) == ("1749.21", 13, "134.55")
    items = {i["name"]: i for i in r["items"]}
    assert (items["Miete"]["status"], items["Miete"]["paid_on"]) == ("paid", "2026-11-01")
    assert (items["Strom"]["status"], items["Strom"]["paid_amount"]) == ("paid", "90.00")
    assert (items["Handy"]["status"], items["Handy"]["due_date"]) == ("open", "2026-11-20")
    assert (items["Autokredit"]["kind"], items["Autokredit"]["amount"], items["Autokredit"]["status"]) == (
        "loan", "230.30", "open")
    assert [i["name"] for i in r["items"]] == ["Miete", "Strom", "Handy", "Autokredit"]


def test_gebuchte_rate_veraendert_den_spielraum_nicht_doppelt(client, headers, szenario, monkeypatch):
    loan = szenario["loan"]
    client.post(f"/loans/{loan['id']}/payments", json={"booking_date": "2026-11-30", "amount": "230.30"},
                headers=headers)
    monkeypatch.setattr(clock, "today", lambda: date(2026, 12, 1))
    r = client.get("/budget/month", params={"month": "2026-11-15"}, headers=headers).json()
    # Zinsanteil 41,67 ist Ausgabe, steckt aber schon in der Rate → variabel bleibt 55,50
    assert (r["variable_spent"], r["available"], r["days_left"], r["available_per_day"]) == (
        "55.50", "1749.21", 0, None)
    rate = next(i for i in r["items"] if i["kind"] == "loan")
    assert (rate["status"], rate["paid_amount"], rate["paid_on"]) == ("paid", "230.30", "2026-11-30")
    handy = next(i for i in r["items"] if i["name"] == "Handy")
    assert handy["status"] == "overdue"


def test_ausgesetzte_rate_und_inaktive_fixkosten_zaehlen_nicht(client, headers, szenario):
    loan = szenario["loan"]
    client.post(f"/loans/{loan['id']}/schedule/1/skip", headers=headers)
    handy = next(f for f in client.get("/fixed-costs", headers=headers).json() if f["name"] == "Handy")
    client.patch(f"/fixed-costs/{handy['id']}", json={"active": False}, headers=headers)
    r = client.get("/budget/month", headers=headers).json()
    assert r["fixed_total"] == "940.00"  # nur Miete + Strom
    assert [i["name"] for i in r["items"]] == ["Miete", "Strom"]


def test_jede_zahlung_zaehlt_nur_fuer_eine_fixkost(client, headers, szenario):
    _fixed(client, headers, name="Miete Garage", amount="60.00", due_day=1, category_id=szenario["miete"]["id"])
    r = client.get("/budget/month", headers=headers).json()
    items = {i["name"]: i for i in r["items"]}
    assert items["Miete"]["status"] == "paid"
    assert items["Miete Garage"]["status"] == "overdue"  # die 850 € sind schon der Miete zugeordnet


def test_fixkosten_validierung_und_isolation(client, headers, other_user, szenario):
    gehalt = next(c for c in client.get("/categories", headers=headers).json() if c["name"] == "Gehalt-Test")
    cases = [
        ({"name": "X", "amount": "1.00", "due_day": 1, "category_id": gehalt["id"]}, 422, "fixed_cost_category_type"),
        ({"name": "Miete", "amount": "1.00", "due_day": 1}, 409, "conflict"),
        ({"name": "Y", "amount": "0", "due_day": 1}, 422, "validation_error"),
        ({"name": "Y", "amount": "1.00", "due_day": 32}, 422, "validation_error"),
        ({"name": "Y", "amount": "1.00", "due_day": 1, "start_date": "2026-05-01", "end_date": "2026-04-01"}, 422,
         "validation_error"),
    ]
    for payload, status, code in cases:
        response = client.post("/fixed-costs", json=payload, headers=headers)
        assert response.status_code == status, payload
        assert response.json()["error"]["code"] == code
    miete = next(f for f in client.get("/fixed-costs", headers=headers).json() if f["name"] == "Miete")
    fremd = other_user["headers"]
    assert client.get(f"/fixed-costs/{miete['id']}", headers=fremd).status_code == 404
    assert client.get("/fixed-costs", headers=fremd).json() == []
    assert client.get("/budget/month", headers=fremd).json()["fixed_total"] == "0.00"
    # Kategorie mit Fixkost ist in Verwendung
    response = client.delete(f"/categories/{szenario['miete']['id']}", headers=headers)
    assert response.json()["error"]["details"]["fixed_costs"] == 1


def test_start_und_ende_einer_fixkost(client, headers, szenario):
    _fixed(client, headers, name="Fitness", amount="30.00", due_day=5, start_date="2026-12-01")
    _fixed(client, headers, name="Altvertrag", amount="10.00", due_day=5, end_date="2026-10-31")
    names = [i["name"] for i in client.get("/budget/month", headers=headers).json()["items"]]
    assert "Fitness" not in names and "Altvertrag" not in names


# --- Wanddisplay -------------------------------------------------------------------


@pytest.fixture
def wall_client(connection):
    def make(host: str) -> TestClient:
        def request_session():
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = request_session
        return TestClient(app, client=(host, 50000))

    yield make
    app.dependency_overrides.clear()


def test_wanddisplay_zeigt_alle_profile(client, headers, szenario, make_user, wall_client):
    lea = make_user("Lea")
    _fixed(client, lea["headers"], name="Handy Lea", amount="15.00", due_day=25)
    r = wall_client("192.168.1.20").get("/wall")
    assert r.status_code == 200, r.text
    wall = r.json()
    assert (wall["month"], wall["as_of"]) == ("2026-11-01", "2026-11-18")
    profiles = {p["name"]: p for p in wall["profiles"]}
    assert profiles["Alex"]["available"] == "1749.21"
    assert [i["name"] for i in profiles["Alex"]["upcoming"]] == ["Handy", "Autokredit"]
    assert profiles["Lea"]["available"] == "-15.00" and profiles["Lea"]["open_items"] == 1
    loan = wall["loans"][0]
    details = client.get(f"/loans/{szenario['loan']['id']}", headers=headers).json()
    assert (loan["profile_name"], loan["name"], loan["remaining_debt"]) == ("Alex", "Autokredit", "10000.00")
    assert (loan["remaining_installments"], loan["payoff_date"]) == (48, details["final_due_date"])
    assert "items" not in profiles["Alex"]  # keine einzelnen Buchungen an der Wand


@pytest.mark.parametrize("host", ["8.8.8.8", "testclient"])
def test_wanddisplay_nur_im_lokalen_netz(wall_client, host, today):
    response = wall_client(host).get("/wall")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "wall_local_only"
