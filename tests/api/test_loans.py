"""Kredite: Anlage, Tilgungsplan, Raten (Zins/Tilgung getrennt), Storno, Pause, Belastungen."""

from decimal import Decimal

import pytest


def _loan(client, headers, **extra):
    payload = {
        "name": "Autokredit",
        "loan_type": "annuity",
        "lender_name": "Autobank",
        "annual_interest_rate": "5",
        "current_balance": "10000.00",
        "balance_date": "2026-01-01",
        "first_due_date": "2026-01-31",
        "term_months": 48,
        **extra,
    }
    response = client.post("/loans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _schedule(client, headers, loan_id):
    return client.get(f"/loans/{loan_id}/schedule", headers=headers).json()


def _pay(client, headers, loan_id, **payload):
    return client.post(f"/loans/{loan_id}/payments", json=payload, headers=headers)


def _balance(client, headers, account_id, as_of="2099-12-31"):
    return client.get(f"/accounts/{account_id}", params={"as_of": as_of}, headers=headers).json()["balance"]


def _cat_id(client, headers, key):
    return next(c["id"] for c in client.get("/categories", headers=headers).json() if c["system_key"] == key)


# --- Anlage & Plan -------------------------------------------------------------


def test_annuitaet_aus_laufzeit(client, headers):
    loan = _loan(client, headers)
    assert loan["installment_amount"] == "230.30"  # auf den Cent aufgerundet
    assert loan["remaining_debt"] == "10000.00"
    assert loan["open_installments"] == 48
    assert loan["final_due_date"] == "2029-12-31"
    assert _balance(client, headers, loan["account_id"]) == "-10000.00"

    plan = _schedule(client, headers, loan["id"])
    assert len(plan) == 48
    first, second, last = plan[0], plan[1], plan[-1]
    assert (first["due_date"], first["planned_interest"], first["planned_principal"]) == (
        "2026-01-31", "41.67", "188.63",
    )
    assert second["due_date"] == "2026-02-28"  # Monatsende begrenzt
    assert last["planned_remaining_after"] == "0.00"
    assert Decimal(last["planned_installment"]) <= Decimal("230.30")
    assert sum(Decimal(e["planned_principal"]) for e in plan) == Decimal("10000.00")


def test_rate_und_laufzeit_muessen_passen(client, headers):
    # Bank rundet kaufmännisch (230,29): Rundungsrest wird Teil der Schlussrate
    loan = _loan(client, headers, installment_amount="230.29")
    plan = _schedule(client, headers, loan["id"])
    assert len(plan) == 48 and plan[-1]["planned_remaining_after"] == "0.00"

    response = client.post(
        "/loans",
        json={"name": "K2", "loan_type": "annuity", "lender_name": "Bank", "annual_interest_rate": "5",
              "current_balance": "10000.00", "balance_date": "2026-01-01", "term_months": 48,
              "installment_amount": "250.00"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "loan_terms_inconsistent"


def test_rate_deckt_zinsen_nicht(client, headers):
    response = client.post(
        "/loans",
        json={"name": "K", "loan_type": "annuity", "lender_name": "Bank", "annual_interest_rate": "6",
              "current_balance": "100000.00", "balance_date": "2026-01-01", "installment_amount": "400.00"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "never_amortizes"


def test_tilgungsdarlehen_rate_sinkt(client, headers):
    loan = _loan(client, headers, loan_type="installment", annual_interest_rate="6",
                 current_balance="1200.00", term_months=12)
    assert loan["fixed_principal"] == "100.00" and loan["installment_amount"] is None
    plan = _schedule(client, headers, loan["id"])
    assert [e["planned_interest"] for e in plan[:3]] == ["6.00", "5.50", "5.00"]  # 0,5 % p. M.
    assert [e["planned_installment"] for e in plan[:2]] == ["106.00", "105.50"]
    assert len(plan) == 12


def test_null_prozent_finanzierung_mit_rundungsrest(client, headers):
    loan = _loan(client, headers, loan_type="installment", annual_interest_rate="0",
                 current_balance="1000.00", term_months=3)
    plan = _schedule(client, headers, loan["id"])
    assert [e["planned_principal"] for e in plan] == ["333.34", "333.34", "333.32"]
    assert all(e["planned_interest"] == "0.00" for e in plan)


def test_privatkredit_ohne_plan(client, headers):
    loan = _loan(client, headers, loan_type="private", annual_interest_rate="0",
                 current_balance="3000.00", term_months=None)
    assert loan["open_installments"] == 0 and loan["next_due_date"] is None
    assert _schedule(client, headers, loan["id"]) == []


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"loan_type": "installment", "installment_amount": "100.00", "term_months": None}, "invalid_plan_basis"),
        ({"loan_type": "annuity", "fixed_principal": "100.00"}, "invalid_plan_basis"),
        ({"term_months": None}, "invalid_plan_basis"),
        ({"first_due_date": "2025-12-31"}, "first_due_before_balance_date"),
    ],
)
def test_ungueltige_konditionen(client, headers, extra, code):
    payload = {"name": "K", "loan_type": "annuity", "lender_name": "Bank", "annual_interest_rate": "5",
               "current_balance": "1000.00", "balance_date": "2026-01-01", "term_months": 12, **extra}
    response = client.post("/loans", json=payload, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_neuer_kredit_mit_auszahlung(client, headers, make_account):
    giro = make_account(opening_balance="500.00")
    loan = _loan(client, headers, disbursement_account_id=giro["id"], payment_account_id=giro["id"])
    assert _balance(client, headers, giro["id"]) == "10500.00"
    assert _balance(client, headers, loan["account_id"]) == "-10000.00"
    tx = client.get("/transactions", params={"account_ids": [giro["id"]]}, headers=headers).json()["items"][0]
    assert tx["kind"] == "transfer" and tx["source"] == "loan"
    assert client.delete(f"/transactions/{tx['id']}", headers=headers).status_code == 409

    # Löschen ohne Raten entfernt auch die Auszahlung
    assert client.delete(f"/loans/{loan['id']}", headers=headers).status_code == 204
    assert _balance(client, headers, giro["id"]) == "500.00"
    assert client.get(f"/accounts/{loan['account_id']}", headers=headers).status_code == 404


def test_kreditkonto_nicht_manuell_bebuchbar(client, headers):
    loan = _loan(client, headers)
    response = client.post(
        "/transactions",
        json={"account_id": loan["account_id"], "booking_date": "2026-02-01", "amount": "-5.00", "description": "x"},
        headers=headers,
    )
    assert response.json()["error"]["code"] == "loan_account_via_loans"
    assert client.delete(f"/accounts/{loan['account_id']}", headers=headers).status_code == 422


# --- Raten ---------------------------------------------------------------------


def test_rate_wird_in_zins_und_tilgung_aufgeteilt(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"])
    response = _pay(client, headers, loan["id"], booking_date="2026-01-31", amount="230.30")
    assert response.status_code == 201, response.text
    payment = response.json()
    assert (payment["interest"], payment["principal"], payment["extra"]) == ("41.67", "188.63", "0.00")
    assert payment["schedule_seq"] == 1

    assert _balance(client, headers, giro["id"]) == "4769.70"
    assert _balance(client, headers, loan["account_id"]) == "-9811.37"

    tx = client.get(f"/transactions/{payment['payment_transaction_id']}", headers=headers).json()
    assert tx["category_source"] == "loan" and tx["review_status"] == "confirmed"
    assert [(s["amount"], s["kind"]) for s in tx["splits"]] == [("-188.63", "transfer"), ("-41.67", "regular")]
    assert tx["splits"][1]["category_id"] == _cat_id(client, headers, "loan_interest")

    # Gebuchte Rate ist geschützt
    response = client.patch(f"/transactions/{tx['id']}", json={"description": "x"}, headers=headers)
    assert response.json()["error"]["code"] == "loan_payment_via_loans"

    plan = _schedule(client, headers, loan["id"])
    assert plan[0]["status"] == "paid" and plan[0]["payment_id"] == payment["id"]
    assert plan[1]["planned_interest"] == "40.88"  # 9811,37 × 5 % / 12
    view = client.get(f"/loans/{loan['id']}", headers=headers).json()
    assert view["remaining_debt"] == "9811.37" and view["open_installments"] == 47


def test_abweichende_rate_plan_ab_tatsaechlicher_restschuld(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"])
    # Bank bucht 41,50 Zinsen statt 41,67 (taggenau) – Aufteilung wird überschrieben
    response = _pay(client, headers, loan["id"], booking_date="2026-01-31", amount="230.30",
                    interest="41.50", principal="188.80", extra="0.00")
    assert response.status_code == 201
    assert client.get(f"/loans/{loan['id']}", headers=headers).json()["remaining_debt"] == "9811.20"
    plan = _schedule(client, headers, loan["id"])
    assert plan[1]["planned_interest"] == "40.88"  # 9811,20 × 5 % / 12 = 40,88
    assert sum(Decimal(e["planned_principal"]) for e in plan if e["status"] == "planned") == Decimal("9811.20")

    response = _pay(client, headers, loan["id"], booking_date="2026-02-28", amount="230.30",
                    interest="40.00", principal="100.00", extra="0.00")
    assert response.json()["error"]["code"] == "split_sum_mismatch"


def test_vorhandene_buchung_als_rate_verknuepfen_und_stornieren(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers)
    tx = client.post(
        "/transactions",
        json={"account_id": giro["id"], "booking_date": "2026-01-31", "amount": "-230.30",
              "description": "Lastschrift Autobank"},
        headers=headers,
    ).json()
    payment = _pay(client, headers, loan["id"], transaction_id=tx["id"]).json()
    assert payment["principal"] == "188.63"
    assert _pay(client, headers, loan["id"], transaction_id=tx["id"]).status_code == 409

    # Storno: Tilgung verschwindet, die Lastschrift bleibt als offene Buchung
    assert client.delete(f"/loans/{loan['id']}/payments/{payment['id']}", headers=headers).status_code == 204
    restored = client.get(f"/transactions/{tx['id']}", headers=headers).json()
    assert restored["splits"] == [] and restored["review_status"] == "needs_review"
    assert _balance(client, headers, loan["account_id"]) == "-10000.00"
    assert _schedule(client, headers, loan["id"])[0]["status"] == "planned"


def test_storno_nur_letzte_rate_und_eigene_zahlung_wird_geloescht(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"])
    p1 = _pay(client, headers, loan["id"], booking_date="2026-01-31", amount="230.30").json()
    p2 = _pay(client, headers, loan["id"], booking_date="2026-02-28", amount="230.30").json()
    assert p2["schedule_seq"] == 2
    response = client.delete(f"/loans/{loan['id']}/payments/{p1['id']}", headers=headers)
    assert response.json()["error"]["code"] == "payment_not_latest"
    client.delete(f"/loans/{loan['id']}/payments/{p2['id']}", headers=headers)
    assert client.get(f"/transactions/{p2['payment_transaction_id']}", headers=headers).status_code == 404
    assert _balance(client, headers, giro["id"]) == "4769.70"


def test_gebuehren_werden_zuerst_bedient(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"], extra_amount="9.70")
    assert _schedule(client, headers, loan["id"])[0]["planned_installment"] == "240.00"
    payment = _pay(client, headers, loan["id"], booking_date="2026-01-31", amount="240.00").json()
    assert (payment["extra"], payment["interest"], payment["principal"]) == ("9.70", "41.67", "188.63")
    tx = client.get(f"/transactions/{payment['payment_transaction_id']}", headers=headers).json()
    assert tx["splits"][2]["category_id"] == _cat_id(client, headers, "loan_fees")


def test_privatkredit_freie_zahlung_ohne_zinsen(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, loan_type="private", annual_interest_rate="0",
                 current_balance="3000.00", term_months=None, payment_account_id=giro["id"])
    payment = _pay(client, headers, loan["id"], booking_date="2026-03-15", amount="500.00").json()
    assert (payment["interest"], payment["principal"]) == ("0.00", "500.00")
    tx = client.get(f"/transactions/{payment['payment_transaction_id']}", headers=headers).json()
    assert tx["kind"] == "transfer" and tx["splits"] == []  # nur Tilgung -> keine Aufteilung nötig
    assert client.get(f"/loans/{loan['id']}", headers=headers).json()["remaining_debt"] == "2500.00"


def test_privatkredit_mit_zins_taggenau(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, loan_type="private", annual_interest_rate="3.65",
                 current_balance="1000.00", term_months=None, payment_account_id=giro["id"])
    # 1000 × 3,65 % × 100/365 Tage = 10,00
    payment = _pay(client, headers, loan["id"], booking_date="2026-04-11", amount="110.00").json()
    assert (payment["interest"], payment["principal"]) == ("10.00", "100.00")


def test_ueberzahlung_und_abbezahlt(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, loan_type="private", annual_interest_rate="0",
                 current_balance="300.00", term_months=None, payment_account_id=giro["id"])
    response = _pay(client, headers, loan["id"], booking_date="2026-02-01", amount="300.01")
    assert response.json()["error"]["code"] == "principal_exceeds_debt"
    _pay(client, headers, loan["id"], booking_date="2026-02-01", amount="300.00")
    view = client.get(f"/loans/{loan['id']}", headers=headers).json()
    assert view["status"] == "paid_off" and view["remaining_debt"] == "0.00"
    response = _pay(client, headers, loan["id"], booking_date="2026-03-01", amount="1.00")
    assert response.json()["error"]["code"] == "loan_paid_off"


def test_zahlung_vor_stichtag_abgelehnt(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"], balance_date="2026-03-01",
                 first_due_date="2026-03-31")
    response = _pay(client, headers, loan["id"], booking_date="2026-02-27", amount="230.30")
    assert response.json()["error"]["code"] == "before_opening"


# --- Konditionen, Pause, Belastungen, Übersichten --------------------------------


def test_zinsaenderung_nach_zinsbindung(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"])
    _pay(client, headers, loan["id"], booking_date="2026-01-31", amount="230.30")
    response = client.patch(f"/loans/{loan['id']}", json={"annual_interest_rate": "6", "term_months": 47},
                            headers=headers)
    assert response.status_code == 200, response.text
    plan = _schedule(client, headers, loan["id"])
    assert plan[0]["status"] == "paid" and plan[0]["planned_interest"] == "41.67"  # Historie bleibt
    assert plan[1]["planned_interest"] == "49.06"  # 9811,37 × 6 % / 12
    assert len([e for e in plan if e["status"] == "planned"]) == 47
    assert response.json()["installment_amount"] != loan["installment_amount"]


def test_ratenpause_verschiebt_plan(client, headers):
    loan = _loan(client, headers)
    response = client.post(f"/loans/{loan['id']}/schedule/2/skip", headers=headers)
    assert response.json()["error"]["code"] == "skip_not_next"
    plan = client.post(f"/loans/{loan['id']}/schedule/1/skip", headers=headers).json()
    assert plan[0]["status"] == "skipped"
    assert plan[1]["due_date"] == "2026-02-28" and plan[1]["seq"] == 2
    assert plan[-1]["due_date"] == "2030-01-31"  # ein Monat länger
    plan = client.post(f"/loans/{loan['id']}/schedule/1/unskip", headers=headers).json()
    assert plan[0]["status"] == "planned" and len(plan) == 48


def test_zinsbelastung_auf_kreditkonto(client, headers):
    loan = _loan(client, headers, loan_type="private", annual_interest_rate="2",
                 current_balance="1000.00", term_months=None)
    response = client.post(f"/loans/{loan['id']}/charges",
                           json={"booking_date": "2026-12-31", "amount": "20.00", "charge_type": "interest"},
                           headers=headers)
    assert response.status_code == 201
    charge = response.json()
    assert charge["category_id"] == _cat_id(client, headers, "loan_interest")
    assert client.get(f"/loans/{loan['id']}", headers=headers).json()["remaining_debt"] == "1020.00"
    summary = client.get(f"/loans/{loan['id']}/summary", params={"year": 2026}, headers=headers).json()
    assert summary["interest_charged"] == "20.00" and summary["remaining_debt_end_of_year"] == "1020.00"
    assert client.delete(f"/loans/{loan['id']}", headers=headers).status_code == 409
    assert client.delete(f"/loans/{loan['id']}/charges/{charge['id']}", headers=headers).status_code == 204
    assert client.get(f"/loans/{loan['id']}", headers=headers).json()["remaining_debt"] == "1000.00"


def test_jahresuebersicht_und_faellige_raten(client, headers, make_account):
    giro = make_account(opening_balance="5000.00")
    loan = _loan(client, headers, payment_account_id=giro["id"])
    _pay(client, headers, loan["id"], booking_date="2026-01-31", amount="230.30")
    _pay(client, headers, loan["id"], booking_date="2026-02-28", amount="230.30")
    summary = client.get(f"/loans/{loan['id']}/summary", params={"year": 2026}, headers=headers).json()
    assert summary["payments"] == 2
    assert summary["interest_paid"] == "82.55"  # 41,67 + 40,88
    assert Decimal(summary["interest_paid"]) + Decimal(summary["principal_paid"]) == Decimal("460.60")

    upcoming = client.get("/loans/upcoming", params={"days": 366}, headers=headers).json()
    assert upcoming[0]["seq"] == 3 and upcoming[0]["due_date"] == "2026-03-31"
    assert upcoming[0]["payment_account_id"] == giro["id"]
    view = client.get(f"/loans/{loan['id']}", headers=headers).json()
    assert view["overdue_installments"] >= 0  # abhängig vom heutigen Datum


def test_profil_isolation(client, headers, other_user):
    loan = _loan(client, headers)
    fremd = other_user["headers"]
    assert client.get(f"/loans/{loan['id']}", headers=fremd).status_code == 404
    assert client.get(f"/loans/{loan['id']}/schedule", headers=fremd).status_code == 404
    assert client.get("/loans", headers=fremd).json() == []
    assert _pay(client, fremd, loan["id"], booking_date="2026-01-31", amount="1.00").status_code == 404
