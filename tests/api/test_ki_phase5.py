"""KI-Ausbau Phase 5: Importabdeckung, fehlende/ungewöhnliche Zahlungen (05), erwartete Einnahmen (16),
Kontovorschau (17), Jahreskosten (18)."""

from datetime import date

import pytest

from app import clock
from app.services import calendar_de, coverage
from tests.api.test_imports import COLUMN_MAP, IBAN_A, csv_file, upload

HEUTE = date(2026, 11, 25)


@pytest.fixture(autouse=True)
def heute(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: HEUTE)


@pytest.fixture
def bank(make_institution):
    return make_institution("Sparkasse")


@pytest.fixture
def giro(make_account, bank):
    return make_account("Giro", institution_id=bank["id"], iban=IBAN_A, opening_balance="1000.00",
                        opening_balance_date="2025-01-01")


@pytest.fixture
def profile(client, headers, bank):
    return client.post("/import-profiles", json={"name": "CSV", "institution_id": bank["id"], "format": "csv",
                                                 "column_map": COLUMN_MAP}, headers=headers).json()


def cat(client, headers, name):
    return next(c for c in client.get("/categories", headers=headers).json() if c["name"] == name)


def suggestions(client, headers, kind):
    client.post("/suggestions/refresh", headers=headers)
    return client.get("/suggestions", params={"kind": kind}, headers=headers).json()


# --- Kalender und Abdeckung ----------------------------------------------------------------------


def test_bankarbeitstage_ueberspringen_wochenende_und_feiertage():
    assert calendar_de.is_holiday(date(2026, 4, 3))  # Karfreitag 2026
    assert calendar_de.add_business_days(date(2026, 12, 23), 2) == date(2026, 12, 29)  # 24.–26.12. bankfrei
    assert calendar_de.add_business_days(date(2026, 11, 20), 1) == date(2026, 11, 23)  # Freitag → Montag


def test_abdeckung_vereinigt_importzeitraeume_und_kennt_luecken(client, headers, profile, giro, session):
    upload(client, headers, profile, csv_file(("01.09.2026", "-1,00", "a"), ("30.09.2026", "-1,00", "b")))
    upload(client, headers, profile, csv_file(("02.10.2026", "-1,00", "c"), ("15.10.2026", "-1,00", "d")))
    upload(client, headers, profile, csv_file(("01.11.2026", "-1,00", "e"), ("20.11.2026", "-1,00", "f")))
    ranges = coverage.covered_ranges(session, giro["id"])
    assert ranges == [(date(2026, 9, 1), date(2026, 10, 15)), (date(2026, 11, 1), date(2026, 11, 20))]
    assert coverage.is_covered(session, giro["id"], date(2026, 10, 10))
    assert not coverage.is_covered(session, giro["id"], date(2026, 10, 25))


# --- 05 Fehlende und ungewöhnliche Zahlungen -----------------------------------------------------


def test_fehlende_zahlung_nur_wenn_der_zeitraum_importiert_ist(client, headers, profile, giro):
    client.post("/fixed-costs", json={"name": "Strom", "amount": "80.00", "due_day": 10,
                                      "match_text": "Stadtwerke", "account_id": giro["id"]}, headers=headers)
    upload(client, headers, profile, csv_file(("01.11.2026", "-1,00", "x"), ("05.11.2026", "-1,00", "y")))
    assert suggestions(client, headers, "missing_payment") == []  # Import reicht nur bis 5.11.
    upload(client, headers, profile, csv_file(("21.11.2026", "-2,00", "z")))
    assert suggestions(client, headers, "missing_payment") == []  # Lücke 6.–20.11.: keine Aussage möglich
    upload(client, headers, profile, csv_file(("06.11.2026", "-3,00", "a"), ("24.11.2026", "-4,00", "b")))
    found = suggestions(client, headers, "missing_payment")
    assert len(found) == 1 and found[0]["payload"]["name"] == "Strom"
    assert "noch nicht" in found[0]["reason"]


def test_doppelte_abbuchung_im_selben_zyklus_wird_gemeldet(client, headers, profile, giro):
    client.post("/fixed-costs", json={"name": "Strom", "amount": "80.00", "due_day": 10,
                                      "match_text": "Stadtwerke"}, headers=headers)
    upload(client, headers, profile, csv_file(("10.11.2026", "-80,00", "Abschlag", "Stadtwerke"),
                                              ("12.11.2026", "-80,00", "Abschlag", "Stadtwerke")))
    found = suggestions(client, headers, "unusual_payment")
    assert len(found) == 1 and found[0]["payload"]["type"] == "duplicate"


# --- 16 Erwartete Einnahmen ----------------------------------------------------------------------


def test_regelmaessiges_gehalt_wird_als_erwartete_einnahme_vorgeschlagen(client, headers, giro):
    gehalt = cat(client, headers, "Gehalt & Lohn")
    for month in (8, 9, 10, 11):
        client.post("/transactions", json={"account_id": giro["id"], "booking_date": f"2026-{month:02d}-28",
                                           "amount": "2500.00", "description": "Gehalt", "counterparty": "Arbeitgeber AG",
                                           "category_id": gehalt["id"]}, headers=headers)
    found = suggestions(client, headers, "income_series")
    assert len(found) == 1 and found[0]["payload"]["amount"] == "2500.00"
    accepted = client.post(f"/suggestions/{found[0]['id']}/accept", json={}, headers=headers).json()
    incomes = client.get("/expected-incomes", headers=headers).json()
    assert [(i["id"], i["name"], i["due_day"], i["account_id"]) for i in incomes] == [
        (accepted["result_id"], "Arbeitgeber AG", 28, giro["id"])]


# --- 17 Kontovorschau ----------------------------------------------------------------------------


def test_vorschau_zeigt_erwartete_ereignisse_getrennt_vom_kontostand(client, headers, giro):
    client.post("/fixed-costs", json={"name": "Miete", "amount": "700.00", "due_day": 1,
                                      "account_id": giro["id"]}, headers=headers)
    client.post("/fixed-costs", json={"name": "Handy", "amount": "20.00", "due_day": 27,
                                      "account_id": giro["id"]}, headers=headers)
    client.post("/expected-incomes", json={"name": "Gehalt", "amount": "2000.00", "due_day": 28,
                                           "account_id": giro["id"]}, headers=headers)
    forecast = client.get(f"/accounts/{giro['id']}/forecast", params={"until": "2026-12-02"}, headers=headers).json()
    assert forecast["start_balance"] == "1000.00" and forecast["as_of"] == "2026-11-25"
    events = [(e["date"], e["name"], e["amount"], e["kind"]) for e in forecast["events"]]
    assert events == [("2026-11-27", "Handy", "-20.00", "fixed_cost"),
                      ("2026-11-28", "Gehalt", "2000.00", "expected_income"),
                      ("2026-12-01", "Miete", "-700.00", "fixed_cost")]
    assert forecast["end_balance"] == "2280.00" and forecast["lowest"]["balance"] == "980.00"
    assert forecast["events"][0]["expected"] is True


def test_bezahlte_fixkost_erscheint_nicht_mehr_in_der_vorschau(client, headers, giro):
    client.post("/fixed-costs", json={"name": "Handy", "amount": "20.00", "due_day": 27, "match_text": "Funk",
                                      "account_id": giro["id"]}, headers=headers)
    client.post("/transactions", json={"account_id": giro["id"], "booking_date": "2026-11-24", "amount": "-20.00",
                                       "description": "Funk Mobil"}, headers=headers)
    forecast = client.get(f"/accounts/{giro['id']}/forecast", params={"until": "2026-11-30"}, headers=headers).json()
    assert forecast["events"] == []


# --- 18 Jahreskosten -----------------------------------------------------------------------------


def test_grosser_vorjahresbetrag_ohne_fixkost_wird_als_jahresposten_gemeldet(client, headers, giro):
    client.post("/transactions", json={"account_id": giro["id"], "booking_date": "2025-12-10", "amount": "-389.00",
                                       "description": "Jahresbeitrag", "counterparty": "Kfz-Versicherung AG"},
                headers=headers)
    found = suggestions(client, headers, "annual_cost")
    assert len(found) == 1
    payload = found[0]["payload"]
    assert (payload["amount"], payload["interval_months"], payload["expected_date"]) == ("389.00", 12, "2026-12-10")
    accepted = client.post(f"/suggestions/{found[0]['id']}/accept", json={}, headers=headers).json()
    fc = client.get(f"/fixed-costs/{accepted['result_id']}", headers=headers).json()
    assert (fc["interval_months"], fc["first_due_date"], fc["amount"]) == (12, "2026-12-10", "389.00")
