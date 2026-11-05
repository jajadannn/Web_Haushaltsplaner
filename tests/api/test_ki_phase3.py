"""KI-Ausbau Phase 3: Betragsänderungen (03), Regeln aus Korrekturen (04), gruppierte Prüfung (10),
Reihenfolge der Prüfliste (22)."""

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
    return next(c for c in client.get("/categories", headers=headers).json() if c["name"] == name)


def tx(client, headers, account, day, amount, counterparty, category=None, description="Lastschrift"):
    payload = {"account_id": account["id"], "booking_date": day, "amount": amount, "description": description,
               "counterparty": counterparty}
    if category:
        payload["category_id"] = category["id"]
    response = client.post("/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def budget(client, headers, month):
    return client.get("/budget/month", params={"month": month}, headers=headers).json()


def found(client, headers, kind):
    client.post("/suggestions/refresh", headers=headers)
    return client.get("/suggestions", params={"kind": kind}, headers=headers).json()


# --- 03 Betragsänderungen ------------------------------------------------------------------------


@pytest.fixture
def internet(client, headers, giro):
    fc = client.post("/fixed-costs", json={"name": "Internet", "amount": "39.99", "due_day": 3,
                                           "start_date": "2026-01-01"}, headers=headers).json()

    def pay(month, amount):
        t = tx(client, headers, giro, f"2026-{month:02d}-03", amount, "Netzanbieter")
        response = client.post(f"/fixed-costs/{fc['id']}/payments",
                               json={"transaction_id": t["id"], "due_month": f"2026-{month:02d}-01"}, headers=headers)
        assert response.status_code == 201, response.text

    fc["pay"] = pay
    return fc


def test_betrag_gilt_ab_einem_monat_ohne_fruehere_monate_zu_aendern(client, headers, internet):
    response = client.post(f"/fixed-costs/{internet['id']}/amounts", json={"valid_from": "2026-11-01",
                                                                            "amount": "44.99"}, headers=headers)
    assert response.status_code == 201, response.text
    assert budget(client, headers, "2026-10-01")["items"][0]["amount"] == "39.99"
    assert budget(client, headers, "2026-11-01")["items"][0]["amount"] == "44.99"
    amounts = client.get(f"/fixed-costs/{internet['id']}/amounts", headers=headers).json()
    assert [(a["valid_from"], a["amount"]) for a in amounts] == [("2026-01-01", "39.99"), ("2026-11-01", "44.99")]


def test_einmalige_abweichung_wird_nur_gemeldet(client, headers, internet):
    for month, amount in ((9, "-39.99"), (10, "-39.99"), (11, "-52.00")):
        internet["pay"](month, amount)
    changes = found(client, headers, "fixed_cost_change")
    assert len(changes) == 1 and changes[0]["payload"]["change"] == "einmalig"
    accepted = client.post(f"/suggestions/{changes[0]['id']}/accept", json={}, headers=headers)
    assert accepted.status_code == 200
    assert client.get(f"/fixed-costs/{internet['id']}", headers=headers).json()["amount"] == "39.99"


def test_dauerhafte_preisaenderung_wird_ab_monat_vorgeschlagen(client, headers, internet):
    for month, amount in ((8, "-39.99"), (9, "-39.99"), (10, "-44.99"), (11, "-44.99")):
        internet["pay"](month, amount)
    changes = found(client, headers, "fixed_cost_change")
    assert len(changes) == 1
    payload = changes[0]["payload"]
    assert (payload["change"], payload["new_amount"], payload["valid_from"]) == ("dauerhaft", "44.99", "2026-10-01")
    client.post(f"/suggestions/{changes[0]['id']}/accept", json={}, headers=headers)
    assert budget(client, headers, "2026-09-01")["items"][0]["amount"] == "39.99"
    assert budget(client, headers, "2026-11-01")["items"][0]["amount"] == "44.99"
    # nach der Übernahme wird nichts mehr vorgeschlagen
    assert [s["status"] for s in found(client, headers, "fixed_cost_change")] == ["accepted"]


# --- 04 Regeln aus Korrekturen -------------------------------------------------------------------


def test_dreimal_gleich_bestaetigt_ergibt_regelvorschlag(client, headers, giro):
    tanken = cat(client, headers, "Kraftstoff & Ladestrom")
    for day in ("2026-10-02", "2026-10-16", "2026-11-03"):
        tx(client, headers, giro, day, "-50.00", "ARAL Tankstelle 123", tanken)
    rules = found(client, headers, "rule")
    assert len(rules) == 1
    payload = rules[0]["payload"]
    assert payload["target_category_id"] == tanken["id"] and "aral" in payload["pattern"].lower()
    assert rules[0]["evidence"]["confirmed"] == 3
    accepted = client.post(f"/suggestions/{rules[0]['id']}/accept", json={}, headers=headers).json()
    rule = client.get(f"/mapping-rules/{accepted['result_id']}", headers=headers).json()
    assert rule["target_category_id"] == tanken["id"]
    # neue Buchung wird jetzt automatisch zugeordnet
    new = tx(client, headers, giro, "2026-11-18", "-48.00", "ARAL Tankstelle 123")
    client.post("/mapping-rules/apply", params={"dry_run": False}, headers=headers)
    assert client.get(f"/transactions/{new['id']}", headers=headers).json()["category_id"] == tanken["id"]


def test_zwei_bestaetigungen_oder_uneinheitliche_kategorien_ergeben_keine_regel(client, headers, giro):
    tanken, essen = cat(client, headers, "Kraftstoff & Ladestrom"), cat(client, headers, "Lebensmittel")
    tx(client, headers, giro, "2026-10-02", "-50.00", "ARAL Tankstelle", tanken)
    tx(client, headers, giro, "2026-10-09", "-50.00", "ARAL Tankstelle", tanken)
    assert found(client, headers, "rule") == []
    tx(client, headers, giro, "2026-10-16", "-12.00", "ARAL Tankstelle", essen)
    tx(client, headers, giro, "2026-10-23", "-12.00", "ARAL Tankstelle", essen)
    assert found(client, headers, "rule") == []


# --- 10 Gruppierte Prüfung und 22 Reihenfolge ----------------------------------------------------


def test_offene_buchungen_werden_nach_gegenpartei_gruppiert(client, headers, giro):
    for day in ("2026-11-01", "2026-11-08", "2026-11-15"):
        tx(client, headers, giro, day, "-9.99", "Mobilfunk AG")
    tx(client, headers, giro, "2026-11-10", "120.00", "Mobilfunk AG")  # Gutschrift: eigene Gruppe
    tx(client, headers, giro, "2026-11-11", "-3.00", "Bäcker")
    groups = client.get("/review/groups", headers=headers).json()
    assert [(g["label"], g["direction"], g["count"]) for g in groups] == [("Mobilfunk AG", "out", 3)]
    assert len(groups[0]["transaction_ids"]) == 3 and groups[0]["total"] == "-29.97"


def test_pruefliste_nach_klaerungsbedarf_sortiert_mit_begruendung(client, headers, giro):
    klein = tx(client, headers, giro, "2026-11-01", "-3.00", "Bäcker")
    gross = tx(client, headers, giro, "2026-11-02", "-480.00", "Werkstatt")
    for day in ("2026-11-03", "2026-11-04", "2026-11-05"):
        tx(client, headers, giro, day, "-9.99", "Mobilfunk AG")
    page = client.get("/review", params={"order": "priority"}, headers=headers).json()
    ids = [i["transaction"]["id"] for i in page["items"]]
    assert ids[0] == gross["id"] and ids[-1] == klein["id"]
    assert all(i["priority_reason"] for i in page["items"])
    assert page["total"] == 5
