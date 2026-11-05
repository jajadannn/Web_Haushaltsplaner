"""KI-Ausbau Phase 1: Fixkosten mit Rhythmus, feste Zahlungsverknüpfung, Vorschläge, Erkennung."""

from datetime import date

import pytest

from app import clock

HEUTE = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def heute(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: HEUTE)


@pytest.fixture
def giro(make_account):
    return make_account("Giro", opening_balance="5000.00", opening_balance_date="2025-01-01")


def cat(client, headers, name):
    """Standardkategorie nach Namen (wird beim Anlegen des Profils erzeugt)."""
    return next(c for c in client.get("/categories", headers=headers).json() if c["name"] == name)


def tx(client, headers, account, day, amount, counterparty=None, category=None, description="Lastschrift", **extra):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount, "description": description,
               "counterparty": counterparty, **extra}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def fixed(client, headers, **payload):
    response = client.post("/fixed-costs", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def budget(client, headers, month):
    response = client.get("/budget/month", params={"month": month}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def refresh(client, headers):
    response = client.post("/suggestions/refresh", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def suggestions(client, headers, **params):
    return client.get("/suggestions", params={"kind": "fixed_cost_new", **params}, headers=headers).json()


# --- Fixkostenmodell ---------------------------------------------------------------------------


def test_quartalsposten_zaehlt_nur_im_faelligkeitsmonat_sonst_ruecklage(client, headers, giro):
    versicherung = fixed(client, headers, name="Hausrat", amount="90.00", due_day=15, interval_months=3,
                         first_due_date="2026-10-15")
    assert versicherung["interval_months"] == 3
    oktober = budget(client, headers, "2026-10-01")
    assert [i["name"] for i in oktober["items"]] == ["Hausrat"] and oktober["fixed_total"] == "90.00"
    november = budget(client, headers, "2026-11-01")
    assert november["items"] == [] and november["fixed_total"] == "0.00"
    assert november["reserves"] == [{"fixed_cost_id": versicherung["id"], "name": "Hausrat",
                                     "monthly_reserve": "30.00", "next_due_date": "2027-01-15"}]
    assert budget(client, headers, "2027-01-01")["fixed_total"] == "90.00"


def test_rhythmus_ohne_erste_faelligkeit_wird_abgelehnt(client, headers):
    response = client.post("/fixed-costs", json={"name": "X", "amount": "10.00", "due_day": 1, "interval_months": 3},
                           headers=headers)
    assert response.status_code == 422


def test_verknuepfte_zahlung_hat_vorrang_und_zaehlt_nur_einmal(client, headers, giro):
    strom = fixed(client, headers, name="Strom", amount="80.00", due_day=10, match_text="Stadtwerke")
    gas = fixed(client, headers, name="Gas", amount="80.00", due_day=12, match_text="Stadtwerke")
    erste = tx(client, headers, giro, "2026-11-10", "-80.00", "Stadtwerke Musterstadt")
    tx(client, headers, giro, "2026-11-12", "-81.00", "Stadtwerke Musterstadt")
    link = client.post(f"/fixed-costs/{gas['id']}/payments",
                       json={"transaction_id": erste["id"], "due_month": "2026-11-01"}, headers=headers)
    assert link.status_code == 201, link.text
    items = {i["name"]: i for i in budget(client, headers, "2026-11-01")["items"]}
    assert items["Gas"]["paid_amount"] == "80.00" and items["Gas"]["linked"] is True
    assert items["Strom"]["paid_amount"] == "81.00" and items["Strom"]["linked"] is False  # nicht doppelt
    # dieselbe Buchung kann keiner zweiten Fixkost zugeordnet werden
    again = client.post(f"/fixed-costs/{strom['id']}/payments",
                        json={"transaction_id": erste["id"], "due_month": "2026-11-01"}, headers=headers)
    assert again.status_code == 409


def test_buchung_loeschen_loest_die_verknuepfung(client, headers, giro):
    internet = fixed(client, headers, name="Internet", amount="39.99", due_day=3)
    zahlung = tx(client, headers, giro, "2026-11-03", "-39.99", "Netzanbieter")
    client.post(f"/fixed-costs/{internet['id']}/payments",
                json={"transaction_id": zahlung["id"], "due_month": "2026-11-01"}, headers=headers)
    assert client.delete(f"/transactions/{zahlung['id']}", headers=headers).status_code == 204
    item = budget(client, headers, "2026-11-01")["items"][0]
    assert item["status"] != "paid"


def test_verknuepfung_lehnt_zufluss_und_kreditzahlung_ab(client, headers, giro):
    internet = fixed(client, headers, name="Internet", amount="39.99", due_day=3)
    zufluss = tx(client, headers, giro, "2026-11-03", "39.99", "Netzanbieter")
    response = client.post(f"/fixed-costs/{internet['id']}/payments",
                           json={"transaction_id": zufluss["id"], "due_month": "2026-11-01"}, headers=headers)
    assert response.status_code == 422


# --- Erkennung und Vorschläge ------------------------------------------------------------------


@pytest.fixture
def historie(client, headers, giro):
    internet = cat(client, headers, "Internet & Festnetz")
    lebensmittel = cat(client, headers, "Lebensmittel")
    for month in (8, 9, 10, 11):
        tx(client, headers, giro, f"2026-{month:02d}-03", "-39.99", "Netzanbieter GmbH", internet)
        tx(client, headers, giro, f"2026-{month:02d}-05", "-62.40", "Supermarkt Nord", lebensmittel)
    tx(client, headers, giro, "2026-07-15", "-90.00", "Versicherung AG", counterparty_iban="DE89370400440532013000")
    tx(client, headers, giro, "2026-10-15", "-90.00", "Versicherung AG", counterparty_iban="DE89370400440532013000")
    for month in (8, 9, 10):
        tx(client, headers, giro, f"2026-{month:02d}-20", "-15.00", "PayPal Europe", description="Einkauf")
    return {"internet": internet}


def test_erkennung_schlaegt_monatliche_und_quartalsfixkosten_vor(client, headers, historie):
    result = refresh(client, headers)
    assert result["new"] == 2
    found = {s["payload"]["name"]: s for s in suggestions(client, headers, status="open")}
    assert set(found) == {"Netzanbieter GmbH", "Versicherung AG"}
    internet = found["Netzanbieter GmbH"]
    expected = {"amount": "39.99", "interval_months": 1, "due_day": 3, "category_id": historie["internet"]["id"]}
    assert {k: internet["payload"][k] for k in expected} == expected
    assert len(internet["evidence"]["transactions"]) == 4 and internet["reason"]
    versicherung = found["Versicherung AG"]
    assert (versicherung["payload"]["interval_months"], versicherung["payload"]["first_due_date"]) == (3, "2026-07-15")


def test_ablehnung_bleibt_bestehen(client, headers, historie):
    refresh(client, headers)
    internet = next(s for s in suggestions(client, headers) if s["payload"]["name"] == "Netzanbieter GmbH")
    assert client.post(f"/suggestions/{internet['id']}/reject", headers=headers).status_code == 200
    assert refresh(client, headers)["new"] == 0
    statuses = {s["payload"]["name"]: s["status"] for s in suggestions(client, headers)}
    assert statuses["Netzanbieter GmbH"] == "rejected"


def test_uebernehmen_legt_fixkost_mit_verknuepften_zahlungen_an(client, headers, historie):
    refresh(client, headers)
    internet = next(s for s in suggestions(client, headers) if s["payload"]["name"] == "Netzanbieter GmbH")
    response = client.post(f"/suggestions/{internet['id']}/accept", json={"name": "Internet"}, headers=headers)
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["status"] == "accepted" and accepted["result_type"] == "fixed_cost"
    fc = client.get(f"/fixed-costs/{accepted['result_id']}", headers=headers).json()
    assert (fc["name"], fc["amount"], fc["due_day"], fc["start_date"]) == ("Internet", "39.99", 3, "2026-11-01")
    item = budget(client, headers, "2026-11-01")["items"][0]
    assert item["linked"] is True and item["status"] == "paid"
    # zweites Übernehmen: Vorschlag ist nicht mehr offen
    again = client.post(f"/suggestions/{internet['id']}/accept", json={}, headers=headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "suggestion_not_open"
    # die Erkennung schlägt den übernommenen Vertrag nicht erneut vor
    refresh(client, headers)
    assert all(s["payload"]["name"] != "Netzanbieter GmbH" or s["status"] == "accepted"
               for s in suggestions(client, headers))


def test_vorschlag_ohne_belege_wird_veraltet(client, headers, giro):
    ids = [tx(client, headers, giro, f"2026-{m:02d}-07", "-9.99", "Streamingdienst")["id"] for m in (8, 9, 10)]
    refresh(client, headers)
    assert len(suggestions(client, headers, status="open")) == 1
    for tx_id in ids:
        client.delete(f"/transactions/{tx_id}", headers=headers)
    assert refresh(client, headers)["stale"] == 1
    assert suggestions(client, headers)[0]["status"] == "stale"


def test_vorschlaege_sind_profilgetrennt(client, headers, historie, other_user):
    refresh(client, headers)
    first = suggestions(client, headers)[0]
    assert client.get("/suggestions", headers=other_user["headers"]).json() == []
    assert client.post(f"/suggestions/{first['id']}/reject", headers=other_user["headers"]).status_code == 404


def test_zusammenfassung_zaehlt_offene_vorschlaege(client, headers, historie):
    refresh(client, headers)
    assert client.get("/suggestions/summary", headers=headers).json() == {"fixed_cost_new": 2}


# --- Einstellungen je Profil ---------------------------------------------------------------------


def test_profil_einstellungen_haben_vorgaben_und_lassen_sich_aendern(client, headers, user):
    settings = client.get(f"/users/{user['id']}/settings", headers=headers).json()
    assert settings["automation.fixed_cost"] == "suggest"
    response = client.patch(f"/users/{user['id']}/settings", json={"automation.fixed_cost": "dry_run"}, headers=headers)
    assert response.status_code == 200 and response.json()["automation.fixed_cost"] == "dry_run"
    bad = client.patch(f"/users/{user['id']}/settings", json={"automation.fixed_cost": "immer"}, headers=headers)
    assert bad.status_code == 422


# --- Automatik, Probelauf, Rücknahme -------------------------------------------------------------


@pytest.fixture
def eindeutig(client, headers, giro):
    """Drei identische Monatszahlungen mit IBAN und Kategorie – ein eindeutiger Fall."""
    mobil = cat(client, headers, "Mobilfunk")
    for month in (9, 10, 11):
        tx(client, headers, giro, f"2026-{month:02d}-02", "-19.99", "Mobilfunk AG", mobil,
           counterparty_iban="DE02120300000000202051")


def test_probelauf_aendert_nichts_und_markiert_den_vorschlag(client, headers, user, eindeutig):
    client.patch(f"/users/{user['id']}/settings", json={"automation.fixed_cost": "dry_run"}, headers=headers)
    refresh(client, headers)
    assert [s["status"] for s in suggestions(client, headers)] == ["dry_run"]
    assert client.get("/fixed-costs", headers=headers).json() == []


def test_automatik_legt_eindeutige_fixkost_an_und_laesst_sich_zuruecknehmen(client, headers, user, eindeutig):
    client.patch(f"/users/{user['id']}/settings", json={"automation.fixed_cost": "auto"}, headers=headers)
    refresh(client, headers)
    sug = suggestions(client, headers)[0]
    assert sug["status"] == "auto_applied"
    assert [f["name"] for f in client.get("/fixed-costs", headers=headers).json()] == ["Mobilfunk AG"]
    history = client.get("/changes", params={"actor": "auto"}, headers=headers).json()
    assert len(history) == 1 and history[0]["object_type"] == "fixed_cost"
    assert client.post(f"/suggestions/{sug['id']}/revert", headers=headers).status_code == 200
    assert client.get("/fixed-costs", headers=headers).json() == []


def test_ruecknahme_verweigert_nach_manueller_aenderung(client, headers, eindeutig):
    refresh(client, headers)
    sug = suggestions(client, headers)[0]
    accepted = client.post(f"/suggestions/{sug['id']}/accept", json={}, headers=headers).json()
    client.patch(f"/fixed-costs/{accepted['result_id']}", json={"amount": "24.99"}, headers=headers)
    response = client.post(f"/suggestions/{sug['id']}/revert", headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "changed_since"


def test_unklarer_fall_wird_nie_automatisch_uebernommen(client, headers, user, historie):
    client.patch(f"/users/{user['id']}/settings", json={"automation.fixed_cost": "auto"}, headers=headers)
    refresh(client, headers)  # Netzanbieter ohne IBAN, Versicherung vierteljährlich
    assert {s["status"] for s in suggestions(client, headers)} == {"open"}


# --- Parallelität --------------------------------------------------------------------------------


def test_zwei_gleichzeitige_uebernahmen_legen_genau_eine_fixkost_an(engine):
    import threading
    from decimal import Decimal

    from sqlalchemy import text
    from sqlmodel import Session, select

    from app.errors import AppError
    from app.models import Account, FixedCost, Transaction, User
    from app.services import recurring
    from app.services import suggestions as service

    with Session(engine) as s:
        user = User(name="Parallel-KI")
        s.add(user)
        s.commit()
        user_id = user.id
    results = []

    def accept(suggestion_id):
        with Session(engine) as s:
            try:
                service.accept(s, s.get(User, user_id), suggestion_id, {})
                s.commit()
                results.append("ok")
            except AppError as exc:
                results.append(exc.code)

    try:
        with Session(engine) as s:
            user = s.get(User, user_id)
            giro = Account(user_id=user_id, name="Giro-KI", type="checking", opening_balance=Decimal("100"),
                           opening_balance_date=date(2026, 1, 1))
            s.add(giro)
            s.flush()
            for month in (9, 10, 11):
                s.add(Transaction(user_id=user_id, account_id=giro.id, booking_date=date(2026, month, 4),
                                  amount=Decimal("-12.00"), description="Abo", counterparty="Abo-Dienst",
                                  review_status="needs_review", category_source="none", source="manual"))
            s.commit()
            recurring.refresh(s, user, HEUTE)
            s.commit()
            suggestion_id = service.list_suggestions(s, user)[0].id
        threads = [threading.Thread(target=accept, args=(suggestion_id,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        assert sorted(results) == ["ok", "suggestion_not_open"]
        with Session(engine) as s:
            assert len(s.exec(select(FixedCost).where(FixedCost.user_id == user_id)).all()) == 1
    finally:
        with engine.begin() as conn:
            for table in ("change_log", "fixed_cost_payment", "fixed_cost", "suggestion", "analysis_state",
                          '"transaction"', "account", "mapping_rule"):
                conn.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})
            conn.execute(text("UPDATE category SET parent_id = NULL WHERE user_id = :u"), {"u": user_id})
            conn.execute(text("DELETE FROM category WHERE user_id = :u"), {"u": user_id})
            conn.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user_id})
