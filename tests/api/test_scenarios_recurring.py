"""Prüfsatz Fixkostenerkennung: je Szenario Buchungen anlegen, Erkennung laufen lassen, Vorschläge prüfen."""

from datetime import date
from decimal import Decimal

import pytest

from app import clock
from tests.fixtures.scenarios.recurring import SCENARIOS, Scenario

HEUTE = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def heute(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: HEUTE)


def _param(scenario: Scenario):
    marks = [pytest.mark.xfail(reason=scenario.xfail, strict=True)] if scenario.xfail else []
    return pytest.param(scenario, id=scenario.name, marks=marks)


@pytest.mark.parametrize("scenario", [_param(s) for s in SCENARIOS])
def test_szenario(client, headers, make_account, scenario):
    konto = make_account("Giro", opening_balance="5000.00", opening_balance_date="2025-01-01")
    kategorien = {c["name"]: c["id"] for c in client.get("/categories", headers=headers).json()}

    for row in scenario.transactions:
        row = dict(row)
        name = row.pop("category_name", None)
        if name:
            row["category_id"] = kategorien[name]
        response = client.post("/transactions", json={"account_id": konto["id"], **row}, headers=headers)
        assert response.status_code == 201, response.text

    assert client.post("/suggestions/refresh", headers=headers).status_code == 200
    response = client.get("/suggestions", params={"kind": "fixed_cost_new"}, headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()
    items = items["items"] if isinstance(items, dict) else items
    erkannt = sorted(
        (i["payload"]["name"], i["payload"]["interval_months"], Decimal(str(i["payload"]["amount"])),
         i["payload"]["due_day"])
        for i in items
    )
    erwartet = sorted(
        (e.name_contains, e.interval_months, Decimal(e.amount), e.due_day) for e in scenario.expected
    )
    assert len(erkannt) == len(erwartet), f"erkannt: {erkannt}"
    for (name, interval, amount, due_day), (teil, e_interval, e_amount, e_day) in zip(erkannt, erwartet, strict=True):
        assert teil.casefold() in name.casefold()
        assert (interval, amount, due_day) == (e_interval, e_amount, e_day)
