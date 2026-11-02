"""Tilgungsplan-Rechenlogik (`app/services/loans/schedule.py`): reine Funktionen, keine Datenbank.

1. Referenzfälle: Die erwarteten Werte sind unabhängig von den getesteten Funktionen nachgerechnet
   (von Hand bzw. mit exakten Brüchen und ganzzahligen Cent, nicht mit Decimal). Die Rechnung steht
   als Kommentar am Test.
2. Fehlerfälle: `ScheduleError.code`.
3. Eigenschaftstests (Hypothesis) über den ganzen Eingabebereich.

Gefundene Abweichungen wurden behoben; neue wären als `xfail(strict=True)` mit dem minimalen Gegenbeispiel
festgehalten. Sie schlagen deterministisch fehl (Hypothesis führt `@example` zuerst aus). Wird die
Logik korrigiert, meldet pytest XPASS(strict); dann die Markierung entfernen.

Ausführen (ohne Datenbank, daher ohne conftest):
    .venv/bin/python -m pytest tests/unit/test_loan_schedule.py --noconftest -p no:cacheprovider
"""

import calendar
from datetime import date
from decimal import Decimal
from itertools import islice

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from app.services.loans.schedule import (
    MAX_INSTALLMENTS,
    PlannedInstallment,
    ScheduleError,
    accrued_interest,
    add_months,
    annuity_installment,
    build_plan,
    check_term_matches,
    due_dates,
    fixed_principal_for,
    installments_for_term,
    monthly_interest,
    split_payment,
)

D = Decimal
ZERO = D("0.00")
FIRST_DUE = date(2026, 1, 31)
PAYMENT_DAY = 31
LAST_DUE = date(2029, 12, 31)  # Fälligkeit der 48. Rate bei erster Fälligkeit 31.01.2026


def reference_plan(**overrides) -> list[PlannedInstallment]:
    """Plan zu Referenzfall 1 (10.000 € / 5 % / Rate 230,30, ab 31.01.2026, Zahltag 31).

    Einzelne `build_plan`-Parameter lassen sich überschreiben.
    """
    params = {
        "remaining": D("10000.00"),
        "annual_percent": D("5"),
        "first_due": FIRST_DUE,
        "payment_day": PAYMENT_DAY,
        "installment": D("230.30"),
    }
    return build_plan(**(params | overrides))


@pytest.fixture(scope="module")
def annuity_plan() -> list[PlannedInstallment]:
    return reference_plan()


def zero_percent_plan(remaining: str, fixed_principal: str, final_due: date | None = None):
    """0-%-Tilgungsplan ab 31.01.2026: Zinsen sind 0, die Tilgung steuert die Rate allein."""
    return build_plan(
        remaining=D(remaining),
        annual_percent=D("0"),
        first_due=FIRST_DUE,
        payment_day=PAYMENT_DAY,
        fixed_principal=D(fixed_principal),
        final_due=final_due,
    )


# =============================================================================================
# 1. Referenzfälle
# =============================================================================================

# --- Fall 1: Annuitätendarlehen 10.000 € / 5 % p. a. / 48 Monate -----------------------------
#
# Monatszins q = 5 % / 12 = 0,0041666…, (1+q)^48 = 1,2208953…
# Exakte Annuität = 10000 · q / (1 − (1+q)^−48) = 41,6667 / 0,1809290 = 230,29293…
#   → AUFgerundet 230,30 (kaufmännisch gerundet wären es 230,29).
# Rate 1:  Zinsen 10000 · q = 41,666… → 41,67 | Tilgung 230,30 − 41,67 = 188,63 | Rest 9.811,37
# Rate 2:  Zinsen 9811,37 · q = 40,8807… → 40,88 | Tilgung 230,30 − 40,88 = 189,42 | Rest 9.621,95
# Rate 47: Rest danach 229,01
# Rate 48: Zinsen 229,01 · q = 0,9542… → 0,95 | Tilgung = Restschuld 229,01 | Rate 229,96
# Gezahlt: 47 · 230,30 + 229,96 = 11.054,06 → Gesamtzinsen 11.054,06 − 10.000,00 = 1.054,06
# Gegenprobe mit ganzzahligen Cent: 48 Raten, Zinsen zusammen 105.406 Cent.


def test_annuity_installment_is_rounded_up_to_the_cent():
    # exakt 230,29293… → 230,30 und nicht kaufmännisch 230,29
    assert annuity_installment(D("10000.00"), D("5"), 48) == D("230.30")


def test_annuity_plan_has_48_installments(annuity_plan):
    assert len(annuity_plan) == 48
    assert [item.seq for item in annuity_plan] == list(range(1, 49))


def test_annuity_plan_first_installments(annuity_plan):
    first, second = annuity_plan[:2]
    assert (first.seq, first.due_date) == (1, date(2026, 1, 31))
    assert first.interest == D("41.67")
    assert first.principal == D("188.63")
    assert first.extra == ZERO
    assert first.remaining_after == D("9811.37")
    assert first.total == D("230.30")
    assert (second.seq, second.due_date) == (2, date(2026, 2, 28))
    assert second.interest == D("40.88")
    assert second.principal == D("189.42")
    assert second.remaining_after == D("9621.95")


def test_annuity_plan_due_dates_stick_to_payment_day(annuity_plan):
    due = {item.seq: item.due_date for item in annuity_plan}
    assert due[1] == date(2026, 1, 31)
    assert due[2] == date(2026, 2, 28)  # 2026 ist kein Schaltjahr
    assert due[3] == date(2026, 3, 31)  # der Tag springt auf 31 zurück, er driftet nicht auf 28
    assert due[4] == date(2026, 4, 30)
    assert due[26] == date(2028, 2, 29)  # Februar 2028: Schaltjahr
    assert due[48] == LAST_DUE


def test_annuity_plan_totals_are_exact_to_the_cent(annuity_plan):
    assert sum(item.principal for item in annuity_plan) == D("10000.00")
    assert annuity_plan[-1].remaining_after == ZERO
    assert sum(item.interest for item in annuity_plan) == D("1054.06")
    assert sum(item.total for item in annuity_plan) == D("11054.06")


def test_annuity_plan_last_installment_settles_the_exact_remaining_debt(annuity_plan):
    assert all(item.total == D("230.30") for item in annuity_plan[:-1])
    assert annuity_plan[-2].remaining_after == D("229.01")
    last = annuity_plan[-1]
    assert last.interest == D("0.95")
    assert last.principal == D("229.01")
    assert last.remaining_after == ZERO
    assert last.total == D("229.96")
    assert last.total <= D("230.30")


# --- Fall 2: Bankrate 230,29 (kaufmännisch gerundet) und `final_due` ----------------------------
#
# Gegenüber der exakten Annuität 230,2929… fehlen je Rate 0,0029 €; mit den gerundeten Zinsen bleiben
# nach Rate 48 genau 0,19 € Restschuld (Rate 48: Zinsen 0,96 | Tilgung 229,33 | Rest 0,19).
# Zinsen der Mini-Rate: 0,19 · q = 0,0008 → 0,00. Ohne `final_due` folgt also eine 49. Rate über
# 0,19 € (nur Tilgung), fällig 31.01.2030. Mit `final_due` = Fälligkeit der Rate 48 wird die
# Tilgung der Mini-Rate in Rate 48 übernommen: 229,33 + 0,19 = 229,52, Rate 0,96 + 229,52 = 230,48.
# Die Toleranz für den Rest liegt laut Code bei max(1,00 €; 1 % der Rate) = 2,30 €.
# Gesamtzinsen 1.054,11 (ganzzahlige Gegenprobe: 105.411 Cent).


def test_rounded_bank_installment_without_final_due_appends_a_mini_installment():
    plan = reference_plan(installment=D("230.29"))
    assert len(plan) == 49
    assert plan[47].remaining_after == D("0.19")
    mini = plan[48]
    assert (mini.seq, mini.due_date) == (49, date(2030, 1, 31))
    assert (mini.interest, mini.principal, mini.remaining_after) == (ZERO, D("0.19"), ZERO)
    assert sum(item.principal for item in plan) == D("10000.00")
    assert sum(item.interest for item in plan) == D("1054.11")


def test_rounded_bank_installment_with_final_due_is_absorbed_into_the_last_installment():
    plan = reference_plan(installment=D("230.29"), final_due=LAST_DUE)
    assert len(plan) == 48
    last = plan[-1]
    assert (last.seq, last.due_date) == (48, LAST_DUE)
    assert last.interest == D("0.96")
    assert last.principal == D("229.52")
    assert last.total == D("230.48")
    assert last.remaining_after == ZERO
    assert plan[:-1] == reference_plan(installment=D("230.29"))[:47]
    assert sum(item.principal for item in plan) == D("10000.00")
    assert sum(item.interest for item in plan) == D("1054.11")


# Laufzeitende (`final_due`) an kleinen 0-%-Plänen (Raten ab 31.01.2026: 31.01., 28.02., 31.03., 30.04.).
# Die Rate am Laufzeitende ist die Schlussrate und begleicht die GESAMTE Restschuld – es gibt nie
# mehr Raten als vereinbart. 1000,00 € in Raten zu 333,33 €: 3 · 333,33 = 999,99, es bleibt 0,01 €.


def test_single_cent_rest_after_final_due_is_added_to_the_last_installment():
    raw = zero_percent_plan("1000.00", "333.33")
    assert [item.principal for item in raw] == [D("333.33")] * 3 + [D("0.01")]
    merged = zero_percent_plan("1000.00", "333.33", final_due=date(2026, 3, 31))
    assert [item.principal for item in merged] == [D("333.33"), D("333.33"), D("333.34")]
    last = merged[-1]
    assert (last.seq, last.due_date, last.remaining_after) == (3, date(2026, 3, 31), ZERO)


@pytest.mark.parametrize(
    ("final_due", "principals"),
    [
        pytest.param(None, ["333.33", "333.33", "333.33", "0.01"], id="ohne final_due: Mini-Rate"),
        pytest.param(date(2026, 2, 28), ["333.33", "666.67"], id="final_due = 2. Rate: Schlussrate"),
        pytest.param(date(2026, 4, 30), ["333.33", "333.33", "333.33", "0.01"], id="final_due = Mini-Rate"),
        pytest.param(date(2026, 5, 31), ["333.33", "333.33", "333.33", "0.01"], id="final_due nach Planende"),
    ],
)
def test_final_due_installment_settles_the_whole_rest(final_due, principals):
    plan = zero_percent_plan("1000.00", "333.33", final_due=final_due)
    assert [item.principal for item in plan] == [D(p) for p in principals]
    assert plan[-1].remaining_after == ZERO


@pytest.mark.parametrize(
    ("remaining", "fixed_principal", "last_principal"),
    [
        pytest.param("301.00", "100.00", "101.00", id="Rest 1,00"),
        pytest.param("301.01", "100.00", "101.01", id="Rest 1,01"),
        pytest.param("1000.00", "300.00", "400.00", id="Rest 100,00 (keine Toleranzgrenze)"),
        pytest.param("3010.01", "1000.00", "1010.01", id="Rest 10,01"),
    ],
)
def test_closing_installment_takes_any_rest(remaining, fixed_principal, last_principal):
    plan = zero_percent_plan(remaining, fixed_principal, final_due=date(2026, 3, 31))
    assert len(plan) == 3
    assert plan[-1].principal == D(last_principal)
    assert sum(item.principal for item in plan) == D(remaining)


# --- Fall 3: Tilgungsdarlehen 1.200 € / 6 % / 12 Monate, feste Tilgung 100,00 € ----------------
#
# Monatszins 6 % / 12 = 0,5 %: 1200 · 0,5 % = 6,00 | 1100 · 0,5 % = 5,50 | 1000 → 5,00 | … | 100 → 0,50
# Rate = 100,00 + Zinsen = 106,00 / 105,50 / … / 100,50 (sinkt um 0,50 je Monat).
# Gesamtzinsen = 0,5 % · (1200 + 1100 + … + 100) = 0,5 % · 7.800 = 39,00.


def test_installment_loan_has_falling_installments():
    plan = build_plan(
        remaining=D("1200.00"),
        annual_percent=D("6"),
        first_due=date(2026, 1, 15),
        payment_day=15,
        fixed_principal=D("100.00"),
    )
    assert len(plan) == 12
    assert [item.due_date for item in plan] == [date(2026, month, 15) for month in range(1, 13)]
    assert [item.interest for item in plan] == [
        D(x) for x in "6.00 5.50 5.00 4.50 4.00 3.50 3.00 2.50 2.00 1.50 1.00 0.50".split()
    ]
    assert [item.principal for item in plan] == [D("100.00")] * 12
    assert [item.total for item in plan] == [
        D(x)
        for x in "106.00 105.50 105.00 104.50 104.00 103.50 103.00 102.50 102.00 101.50 101.00 100.50".split()
    ]
    assert [item.remaining_after for item in plan] == [
        D(x) for x in "1100 1000 900 800 700 600 500 400 300 200 100 0".split()
    ]
    assert sum(item.interest for item in plan) == D("39.00")
    assert sum(item.total for item in plan) == D("1239.00")


# --- Fall 4: 0-%-Finanzierung 1.000 € / 3 Monate --------------------------------------------------
#
# 1000 / 3 = 333,333… → AUFgerundet 333,34. Raten 333,34 / 333,34 und Rest 1000 − 666,68 = 333,32.


def test_zero_percent_financing_rounds_the_principal_up_and_the_last_installment_takes_the_rest():
    principal = fixed_principal_for(D("1000.00"), 3)
    assert principal == D("333.34")
    plan = build_plan(
        remaining=D("1000.00"),
        annual_percent=D("0"),
        first_due=FIRST_DUE,
        payment_day=PAYMENT_DAY,
        fixed_principal=principal,
    )
    assert [item.principal for item in plan] == [D("333.34"), D("333.34"), D("333.32")]
    assert [item.remaining_after for item in plan] == [D("666.66"), D("333.32"), ZERO]
    assert all(item.interest == ZERO for item in plan)


def test_zero_percent_annuity_installment_rounds_up():
    assert annuity_installment(D("1000.00"), D("0"), 3) == D("333.34")  # 1000/3 = 333,333…
    plan = reference_plan(
        remaining=D("1000.00"), annual_percent=D("0"), installment=D("333.34")
    )
    assert [item.principal for item in plan] == [D("333.34"), D("333.34"), D("333.32")]


def test_exact_division_is_not_rounded_up():
    assert annuity_installment(D("1200.00"), D("0"), 12) == D("100.00")
    assert fixed_principal_for(D("1200.00"), 12) == D("100.00")
    assert fixed_principal_for(D("1000.00"), 1) == D("1000.00")


# --- Fall 5: `extra` (Gebühr/Versicherung 5,00 € je Rate) ---------------------------------------
#
# Zinsen, Tilgung und Restschuld bleiben wie in Fall 1; die Gebühr kommt je Rate dazu und tilgt nicht.
# Rate 1: 41,67 + 188,63 + 5,00 = 235,30 | Rate 48: 0,95 + 229,01 + 5,00 = 234,96
# Summe aller Raten: 11.054,06 + 48 · 5,00 = 11.294,06


def test_extra_is_part_of_every_installment_but_does_not_repay(annuity_plan):
    plan = reference_plan(extra=D("5.00"))
    assert len(plan) == 48
    assert all(item.extra == D("5.00") for item in plan)
    assert [item.interest for item in plan] == [item.interest for item in annuity_plan]
    assert [item.principal for item in plan] == [item.principal for item in annuity_plan]
    assert [item.remaining_after for item in plan] == [item.remaining_after for item in annuity_plan]
    assert plan[0].total == D("235.30")
    assert plan[-1].total == D("234.96")
    assert sum(item.principal for item in plan) == D("10000.00")
    assert sum(item.total for item in plan) == D("11294.06")


def test_extra_does_not_change_the_term_of_the_plan():
    assert len(reference_plan(extra=D("50.00"))) == 48


# --- Fall 6: `add_months` und `due_dates` --------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "day", "expected"),
    [
        pytest.param(date(2026, 1, 31), 1, 31, date(2026, 2, 28), id="31.01. + 1 Monat = 28.02."),
        pytest.param(date(2028, 1, 31), 1, 31, date(2028, 2, 29), id="31.01.2028 + 1 = 29.02. (Schaltjahr)"),
        pytest.param(date(2026, 11, 30), 3, 30, date(2027, 2, 28), id="30.11. + 3 über den Jahreswechsel"),
        pytest.param(date(2027, 11, 30), 3, 30, date(2028, 2, 29), id="30.11.2027 + 3 = 29.02.2028"),
        pytest.param(date(2026, 11, 15), 3, 15, date(2027, 2, 15), id="Zahltag 15 bleibt der 15."),
        pytest.param(date(2026, 12, 31), 1, 31, date(2027, 1, 31), id="Dezember → Januar"),
        pytest.param(date(2026, 3, 31), 1, 31, date(2026, 4, 30), id="Monat mit 30 Tagen"),
        pytest.param(date(2026, 3, 15), 12, 15, date(2027, 3, 15), id="12 Monate"),
        pytest.param(date(2026, 1, 31), 25, 31, date(2028, 2, 29), id="25 Monate = Februar 2028"),
        pytest.param(date(2100, 1, 31), 1, 31, date(2100, 2, 28), id="2100 ist kein Schaltjahr"),
        pytest.param(date(2000, 1, 31), 1, 31, date(2000, 2, 29), id="2000 ist ein Schaltjahr"),
        pytest.param(date(2026, 1, 31), 1, 15, date(2026, 2, 15), id="Tag stammt aus `day`, nicht aus start"),
        pytest.param(date(2026, 5, 10), 0, 31, date(2026, 5, 31), id="0 Monate setzt nur den Tag"),
    ],
)
def test_add_months(start, months, day, expected):
    assert add_months(start, months, day) == expected


def test_due_dates_start_with_the_first_due_date_unchanged():
    dates = list(islice(due_dates(date(2026, 1, 10), 31), 3))
    assert dates == [date(2026, 1, 10), date(2026, 2, 28), date(2026, 3, 31)]


def test_due_dates_do_not_drift_after_a_short_month():
    dates = list(islice(due_dates(date(2026, 1, 31), 31), 5))
    assert dates == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]


def test_due_dates_in_a_leap_year():
    assert list(islice(due_dates(date(2028, 1, 31), 31), 2))[1] == date(2028, 2, 29)


def test_due_dates_never_end():
    assert len(list(islice(due_dates(FIRST_DUE, PAYMENT_DAY), MAX_INSTALLMENTS + 1))) == (
        MAX_INSTALLMENTS + 1
    )


# --- Fall 7: `split_payment` ---------------------------------------------------------------------
#
# Rate 1 aus Fall 1 mit Gebühr: Zinsen 41,67 + Tilgung 188,63 + Gebühr 5,00 = 235,30.
# Aufteilung einer tatsächlichen Zahlung: zuerst Gebühren, dann Zinsen, Rest Tilgung.
# Rückgabe: (Zinsen, Tilgung, Gebühren).


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        pytest.param("235.30", ("41.67", "188.63", "5.00"), id="genau die Planrate"),
        pytest.param("3.00", ("0.00", "0.00", "3.00"), id="kleiner als die Gebühr"),
        pytest.param("5.00", ("0.00", "0.00", "5.00"), id="genau die Gebühr"),
        pytest.param("30.00", ("25.00", "0.00", "5.00"), id="kleiner als Gebühr + Zinsen"),
        pytest.param("46.67", ("41.67", "0.00", "5.00"), id="genau Gebühr + Zinsen"),
        pytest.param("46.68", ("41.67", "0.01", "5.00"), id="1 Cent mehr geht in die Tilgung"),
        pytest.param("300.00", ("41.67", "253.33", "5.00"), id="größer als die Rate"),
        pytest.param("0.00", ("0.00", "0.00", "0.00"), id="Zahlung 0"),
    ],
)
def test_split_payment_pays_fees_first_then_interest_then_principal(amount, expected):
    result = split_payment(D(amount), interest_due=D("41.67"), extra_due=D("5.00"))
    assert result == tuple(D(part) for part in expected)


def test_split_payment_without_fees():
    assert split_payment(D("100.00"), interest_due=D("41.67"), extra_due=ZERO) == (
        D("41.67"),
        D("58.33"),
        ZERO,
    )


# --- Fall 8: `accrued_interest` (taggenau act/365) -----------------------------------------------
#
# 1000 € · 3,65 % · 100 Tage / 365 = 36,50 · 100 / 365 = 10,00
# 5000 € · 4 % · 45 / 365 = 24,6575… → 24,66


@pytest.mark.parametrize(
    ("remaining", "percent", "days", "expected"),
    [
        pytest.param("1000.00", "3.65", 100, "10.00", id="1000 · 3,65 % · 100/365 = 10,00"),
        pytest.param("1000.00", "3.65", 365, "36.50", id="ein Jahr = Jahreszins"),
        pytest.param("1000.00", "3.65", 366, "36.60", id="act/365: 366 Tage = 366/365 Jahreszins"),
        pytest.param("5000.00", "4", 45, "24.66", id="24,6575… → 24,66"),
        pytest.param("1000.00", "5", 1, "0.14", id="0,13698… → 0,14"),
        pytest.param("100.00", "1", 1, "0.00", id="0,00274 → 0,00"),
        pytest.param("182.50", "1", 1, "0.01", id="exakt 0,005 → kaufmännisch 0,01"),
        pytest.param("1000.00", "3.65", 0, "0.00", id="0 Tage"),
        pytest.param("1000.00", "3.65", -5, "0.00", id="negative Tage"),
        pytest.param("1000.00", "0", 100, "0.00", id="0 %"),
        pytest.param("1000.00", "0.0000", 100, "0.00", id="0,0000 %"),
    ],
)
def test_accrued_interest(remaining, percent, days, expected):
    result = accrued_interest(D(remaining), D(percent), days)
    assert result == D(expected)
    assert result.as_tuple().exponent == -2


# --- Weitere Rechenschritte -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("remaining", "percent", "expected"),
    [
        pytest.param("10000.00", "5", "41.67", id="41,666… → 41,67"),
        pytest.param("9811.37", "5", "40.88", id="40,8807… → 40,88"),
        pytest.param("100.00", "1", "0.08", id="0,0833… → 0,08"),
        pytest.param("1200.00", "6", "6.00", id="6,00 exakt"),
        pytest.param("500000.00", "15", "6250.00", id="Obergrenze der Eigenschaftstests"),
        pytest.param("10000.00", "0", "0.00", id="0 %"),
        # exakt auf dem halben Cent: kaufmännisch aufrunden (nicht Banker's Rounding)
        pytest.param("1.00", "6", "0.01", id="1 · 0,5 % = 0,005 → 0,01"),
        pytest.param("5.00", "6", "0.03", id="5 · 0,5 % = 0,025 → 0,03 (nicht 0,02)"),
        pytest.param("0.50", "12", "0.01", id="0,5 · 1 % = 0,005 → 0,01"),
    ],
)
def test_monthly_interest_is_rounded_half_up_to_the_cent(remaining, percent, expected):
    result = monthly_interest(D(remaining), D(percent))
    assert result == D(expected)
    assert result.as_tuple().exponent == -2




@pytest.mark.parametrize(
    ("remaining", "percent", "expected"),
    [
        pytest.param("6.00", "13", "0.07", id="6,00 zu 13 %: 0,065"),
        pytest.param("16.50", "4", "0.06", id="16,50 zu 4 %: 0,055"),
        pytest.param("162.00", "7", "0.95", id="162,00 zu 7 %: 0,945"),
        pytest.param("156.00", "5.5", "0.72", id="156,00 zu 5,5 %: 0,715"),
    ],
)
def test_monthly_interest_rounds_exact_half_cents_up(remaining, percent, expected):
    assert monthly_interest(D(remaining), D(percent)) == D(expected)


def test_installments_for_term_derives_installment_or_fixed_principal():
    assert installments_for_term(D("10000.00"), D("5"), 48, annuity=True) == (D("230.30"), None)
    assert installments_for_term(D("1200.00"), D("6"), 12, annuity=False) == (None, D("100.00"))


def test_annuity_installment_for_one_month_covers_debt_and_one_month_of_interest():
    # 10000 · (1 + 0,05/12) = 10041,666… → 10041,67 (aufgerundet) = Restschuld 10000 + Zinsen 41,67
    assert annuity_installment(D("10000.00"), D("5"), 1) == D("10041.67")
    plan = reference_plan(installment=D("10041.67"))
    assert len(plan) == 1
    assert (plan[0].interest, plan[0].principal, plan[0].remaining_after) == (
        D("41.67"),
        D("10000.00"),
        ZERO,
    )


# Exakte Annuität liegt genau auf einem Cent: 1000 · (1 + 0,5 %) = 1005,00 (1 Monat, 6 %);
# 100 · 1,005 = 100,50; 28812 · 1201² / (1200 · 2401) = 14424,01 (2 Monate, 1 %).
# Aufrunden darf einen exakten Cent-Betrag nicht erhöhen (exakte Bruchrechnung, kein Rauschen).


@pytest.mark.parametrize(
    ("remaining", "percent", "term", "expected"),
    [
        pytest.param("100.00", "12", 1, "101.00", id="100 · 1,01 = 101,00"),
        pytest.param("201.00", "12", 2, "102.01", id="201 · 1,01² / 2,01 = 102,01"),
        pytest.param("1000.00", "0", 8, "125.00", id="0 %: 1000 / 8 = 125,00"),
        pytest.param("1000.00", "6", 1, "1005.00", id="1000 · 1,005"),
        pytest.param("100.00", "6", 1, "100.50", id="100 · 1,005"),
        pytest.param("28812.00", "1", 2, "14424.01", id="2 Monate, 1 %"),
    ],
)
def test_annuity_installment_does_not_round_up_an_exact_cent_amount(
    remaining, percent, term, expected
):
    assert annuity_installment(D(remaining), D(percent), term) == D(expected)


# --- Szenarien aus den Abnahmekriterien -----------------------------------------------------------


def test_plan_from_the_current_remaining_debt_continues_the_original_plan(annuity_plan):
    """Laufender Kredit, mitten in der Laufzeit erfasst (oder nach einer Zahlung neu berechnet).

    Nach Rate 12 beträgt die Restschuld 7.683,80 €; Zinsen der Rate 13: 7683,80 · q = 32,0158… → 32,02.
    Ein Plan ab dieser Restschuld mit derselben Rate entspricht den Raten 13 bis 48 des Ursprungsplans.
    """
    assert annuity_plan[11].remaining_after == D("7683.80")
    rebuilt = build_plan(
        remaining=D("7683.80"),
        annual_percent=D("5"),
        first_due=date(2027, 1, 31),
        payment_day=PAYMENT_DAY,
        installment=D("230.30"),
        start_seq=13,
    )
    assert rebuilt[0].interest == D("32.02")
    assert [item.seq for item in rebuilt] == list(range(13, 49))
    assert rebuilt == annuity_plan[12:]


def test_deviating_payment_is_recalculated_and_the_deviation_does_not_add_up(annuity_plan):
    """Rate 13 wird mit 1.000,00 € statt 230,30 € bezahlt (Sondertilgung).

    Zinsen laut Plan 32,02 → Tilgung 1000,00 − 32,02 = 967,98 → neue Restschuld 7683,80 − 967,98 = 6.715,82.
    Neuer Plan ab 28.02.2027: erste Zinsen 6715,82 · q = 27,9826… → 27,98; Referenzrechnung: 32 statt
    35 Raten, letzte Rate 35,85, Zinsen zusammen 459,33. Die Tilgungen ergeben genau die neue Restschuld.
    """
    interest, principal, extra = split_payment(
        D("1000.00"), interest_due=annuity_plan[12].interest, extra_due=ZERO
    )
    assert (interest, principal, extra) == (D("32.02"), D("967.98"), ZERO)
    new_remaining = annuity_plan[11].remaining_after - principal
    assert new_remaining == D("6715.82")
    plan = build_plan(
        remaining=new_remaining,
        annual_percent=D("5"),
        first_due=date(2027, 2, 28),
        payment_day=PAYMENT_DAY,
        installment=D("230.30"),
        start_seq=14,
    )
    assert plan[0].seq == 14
    assert plan[0].interest == D("27.98")
    assert len(plan) == 32
    assert plan[-1].total == D("35.85")
    assert sum(item.interest for item in plan) == D("459.33")
    assert sum(item.principal for item in plan) == new_remaining
    assert plan[-1].remaining_after == ZERO


def test_private_loan_with_free_payments_splits_by_accrued_interest():
    """Privatkredit 5.000 € zu 4 % ohne festen Plan, zwei freie Zahlungen.

    Zahlung 1 nach 45 Tagen: 5000 · 0,04 · 45/365 = 24,6575… → 24,66; Tilgung 500,00 − 24,66 = 475,34.
    Restschuld 4.524,66. Zahlung 2 nach 30 Tagen: 4524,66 · 0,04 · 30/365 = 14,8756… → 14,88;
    Tilgung 1000,00 − 14,88 = 985,12; Restschuld 3.539,54.
    """
    remaining = D("5000.00")
    interest_due = accrued_interest(remaining, D("4"), 45)
    assert interest_due == D("24.66")
    interest, principal, extra = split_payment(D("500.00"), interest_due=interest_due, extra_due=ZERO)
    assert (interest, principal, extra) == (D("24.66"), D("475.34"), ZERO)
    remaining -= principal
    assert remaining == D("4524.66")

    interest_due = accrued_interest(remaining, D("4"), 30)
    assert interest_due == D("14.88")
    interest, principal, extra = split_payment(D("1000.00"), interest_due=interest_due, extra_due=ZERO)
    assert (interest, principal, extra) == (D("14.88"), D("985.12"), ZERO)
    assert remaining - principal == D("3539.54")


def test_build_plan_numbers_installments_from_start_seq():
    plan = reference_plan(start_seq=13)
    assert [item.seq for item in plan[:3]] == [13, 14, 15]
    assert plan[-1].seq == 60


@pytest.mark.parametrize("remaining", [D("0.00"), D("-5.00")])
def test_build_plan_without_remaining_debt_is_empty(remaining):
    assert reference_plan(remaining=remaining) == []


# =============================================================================================
# 2. Fehlerfälle: ScheduleError mit .code
# =============================================================================================


def test_schedule_error_carries_message_code_and_details():
    error = ScheduleError("Nachricht", "irgendein_code", {"a": 1})
    assert isinstance(error, ValueError)
    assert str(error) == "Nachricht"
    assert error.code == "irgendein_code"
    assert error.details == {"a": 1}
    assert ScheduleError("Nachricht", "irgendein_code").details is None


@pytest.mark.parametrize(
    ("percent", "installment"),
    [
        pytest.param("5", "41.67", id="Rate = erste Monatszinsen"),
        pytest.param("5", "30.00", id="Rate < erste Monatszinsen"),
        pytest.param("0", "0.00", id="0 % und Rate 0"),
        pytest.param("0", "-5.00", id="negative Rate"),
    ],
)
def test_installment_not_above_the_first_interest_never_amortizes(percent, installment):
    with pytest.raises(ScheduleError) as caught:
        reference_plan(annual_percent=D(percent), installment=D(installment))
    assert caught.value.code == "never_amortizes"


def test_never_amortizes_reports_installment_and_first_interest():
    # erste Monatszinsen auf 10.000 € zu 5 %: 41,67
    with pytest.raises(ScheduleError) as caught:
        reference_plan(installment=D("41.67"))
    assert caught.value.details == {"installment": D("41.67"), "first_interest": D("41.67")}


@pytest.mark.parametrize(
    ("installment", "fixed_principal"),
    [
        pytest.param(None, None, id="weder Rate noch Tilgung"),
        pytest.param(D("230.30"), D("100.00"), id="Rate und Tilgung"),
        pytest.param(None, D("0.00"), id="Tilgung 0"),
        pytest.param(None, D("-10.00"), id="negative Tilgung"),
    ],
)
def test_plan_needs_exactly_one_positive_basis(installment, fixed_principal):
    with pytest.raises(ScheduleError) as caught:
        reference_plan(installment=installment, fixed_principal=fixed_principal)
    assert caught.value.code == "invalid_plan_basis"


@pytest.mark.parametrize("term", [0, -12])
@pytest.mark.parametrize(
    "derive",
    [
        pytest.param(lambda term: annuity_installment(D("1000.00"), D("5"), term), id="annuity"),
        pytest.param(lambda term: annuity_installment(D("1000.00"), D("0"), term), id="annuity 0 %"),
        pytest.param(lambda term: fixed_principal_for(D("1000.00"), term), id="fixed_principal"),
        pytest.param(
            lambda term: installments_for_term(D("1000.00"), D("5"), term, annuity=True),
            id="installments_for_term annuity",
        ),
        pytest.param(
            lambda term: installments_for_term(D("1000.00"), D("5"), term, annuity=False),
            id="installments_for_term fixed",
        ),
    ],
)
def test_term_without_installments_is_invalid(derive, term):
    with pytest.raises(ScheduleError) as caught:
        derive(term)
    assert caught.value.code == "invalid_term"


def test_matching_term_is_accepted(annuity_plan):
    assert check_term_matches(annuity_plan, 48) is None


@pytest.mark.parametrize("term", [1, 36, 47, 49])
def test_term_not_matching_the_plan_is_inconsistent(annuity_plan, term):
    with pytest.raises(ScheduleError) as caught:
        check_term_matches(annuity_plan, term)
    assert caught.value.code == "loan_terms_inconsistent"
    assert caught.value.details == {"term_months": term, "installments_needed": 48}


def test_bank_installment_matches_the_term_only_with_final_due():
    without_final_due = reference_plan(installment=D("230.29"))
    with pytest.raises(ScheduleError) as caught:
        check_term_matches(without_final_due, 48)
    assert caught.value.code == "loan_terms_inconsistent"
    assert caught.value.details["installments_needed"] == 49
    check_term_matches(reference_plan(installment=D("230.29"), final_due=LAST_DUE), 48)


def test_installment_just_above_the_interest_needs_more_than_600_installments():
    # Zinsen 41,67 → Rate 41,68 tilgt nur 0,01 € je Monat: 10.000 € bräuchten 1.000.000 Raten
    with pytest.raises(ScheduleError) as caught:
        reference_plan(installment=D("41.68"))
    assert caught.value.code == "term_too_long"


def test_term_too_long_for_a_tiny_fixed_principal():
    with pytest.raises(ScheduleError) as caught:
        zero_percent_plan("1000.00", "0.01")
    assert caught.value.code == "term_too_long"


def test_installment_limit_is_exactly_600_installments():
    assert MAX_INSTALLMENTS == 600  # 50 Jahre
    assert len(zero_percent_plan(str(MAX_INSTALLMENTS), "1.00")) == MAX_INSTALLMENTS
    with pytest.raises(ScheduleError) as caught:
        zero_percent_plan(str(MAX_INSTALLMENTS + 1), "1.00")
    assert caught.value.code == "term_too_long"


# =============================================================================================
# 3. Eigenschaftstests (Hypothesis)
# =============================================================================================
#
# Eingabebereich laut Auftrag: Restschuld 100,00 – 500.000,00 €, Zins 0 – 15 % (4 Nachkommastellen),
# Laufzeit 1 – 480 Monate. `database=None`: kein `.hypothesis/`-Archiv im Projektordner.
# `deadline=None`: ein Plan mit 480 Raten ist kein Fehler.

PLAN_PROPERTY = settings(max_examples=300, deadline=None, database=None)
CHEAP_PROPERTY = settings(max_examples=500, deadline=None, database=None)

REMAINING = st.decimals(min_value=D("100.00"), max_value=D("500000.00"), places=2)
ANNUAL_PERCENT = st.decimals(min_value=D("0"), max_value=D("15"), places=4)
TERM = st.integers(min_value=1, max_value=480)
TERM_AT_LEAST_TWO = st.integers(min_value=2, max_value=480)
FIRST_DUES = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))
PAYMENT_DAYS = st.integers(min_value=1, max_value=31)
EXTRAS = st.decimals(min_value=D("0.00"), max_value=D("50.00"), places=2)


def month_number(day: date) -> int:
    return day.year * 12 + day.month - 1


def assert_valid_plan(
    plan: list[PlannedInstallment],
    *,
    remaining: Decimal,
    percent: Decimal,
    first_due: date,
    payment_day: int,
    extra: Decimal = ZERO,
) -> None:
    """Invarianten jedes gültigen Plans."""
    assert plan
    previous = remaining
    for index, item in enumerate(plan):
        assert item.seq == index + 1
        assert item.interest >= 0
        assert item.principal > 0
        assert item.remaining_after >= 0
        # Zinsen immer auf die Restschuld vor der Rate; Restschuld = vorherige − Tilgung
        assert item.interest == monthly_interest(previous, percent)
        assert item.remaining_after == previous - item.principal
        assert item.extra == extra
        assert item.total == item.interest + item.principal + extra
        previous = item.remaining_after
    assert plan[-1].remaining_after == 0
    assert sum(item.principal for item in plan) == remaining

    assert plan[0].due_date == first_due
    for before, after in zip(plan, plan[1:], strict=False):
        assert after.due_date > before.due_date
        assert month_number(after.due_date) - month_number(before.due_date) == 1
        last_day = calendar.monthrange(after.due_date.year, after.due_date.month)[1]
        assert after.due_date.day == min(payment_day, last_day)


@PLAN_PROPERTY
@given(
    remaining=REMAINING,
    percent=ANNUAL_PERCENT,
    term=TERM,
    first_due=FIRST_DUES,
    payment_day=PAYMENT_DAYS,
    extra=EXTRAS,
    with_final_due=st.booleans(),
)
# Grenzen des Eingabebereichs und Referenzfall 1 laufen immer mit
@example(D("500000.00"), D("15"), 480, date(2026, 1, 31), 31, D("50.00"), True)
@example(D("100.00"), D("15"), 480, date(2026, 1, 31), 31, D("0.00"), False)
@example(D("100.00"), D("0"), 1, date(2028, 2, 29), 29, D("0.00"), True)
@example(D("10000.00"), D("5"), 48, date(2026, 1, 31), 31, D("5.00"), False)
def test_annuity_plan_invariants(
    remaining, percent, term, first_due, payment_day, extra, with_final_due
):
    installment = annuity_installment(remaining, percent, term)
    # Randfall: abgeleitete Rate == erste Zinsen, siehe test_derived_annuity_installment_amortizes
    assume(installment > monthly_interest(remaining, percent))
    final_due = add_months(first_due, term - 1, payment_day) if with_final_due else None
    plan = build_plan(
        remaining=remaining,
        annual_percent=percent,
        first_due=first_due,
        payment_day=payment_day,
        installment=installment,
        extra=extra,
        final_due=final_due,
    )
    assert_valid_plan(
        plan,
        remaining=remaining,
        percent=percent,
        first_due=first_due,
        payment_day=payment_day,
        extra=extra,
    )
    # alle Raten bis auf die letzte sind die feste Rate; die letzte begleicht die exakte Restschuld
    assert all(item.interest + item.principal == installment for item in plan[:-1])
    if final_due is None:
        assert plan[-1].interest + plan[-1].principal <= installment


@PLAN_PROPERTY
@given(
    remaining=REMAINING,
    percent=ANNUAL_PERCENT,
    term=TERM,
    first_due=FIRST_DUES,
    payment_day=PAYMENT_DAYS,
    extra=EXTRAS,
)
@example(D("500000.00"), D("15"), 480, date(2026, 1, 31), 31, D("50.00"))
@example(D("100.00"), D("15"), 480, date(2026, 1, 31), 31, D("0.00"))
@example(D("100.00"), D("0"), 1, date(2028, 2, 29), 29, D("0.00"))
@example(D("1200.00"), D("6"), 12, date(2026, 1, 15), 15, D("0.00"))
def test_fixed_principal_plan_invariants(remaining, percent, term, first_due, payment_day, extra):
    fixed_principal = fixed_principal_for(remaining, term)
    plan = build_plan(
        remaining=remaining,
        annual_percent=percent,
        first_due=first_due,
        payment_day=payment_day,
        fixed_principal=fixed_principal,
        extra=extra,
    )
    assert_valid_plan(
        plan,
        remaining=remaining,
        percent=percent,
        first_due=first_due,
        payment_day=payment_day,
        extra=extra,
    )
    assert all(item.principal == fixed_principal for item in plan[:-1])
    assert plan[-1].principal <= fixed_principal
    # die Rate sinkt (Zinsen auf die kleiner werdende Restschuld) und steigt nie
    assert all(after.total <= before.total for before, after in zip(plan, plan[1:], strict=False))


@CHEAP_PROPERTY
@given(first_due=FIRST_DUES, payment_day=PAYMENT_DAYS)
def test_due_dates_are_strictly_monthly_and_follow_the_payment_day(first_due, payment_day):
    dates = list(islice(due_dates(first_due, payment_day), 40))
    assert dates[0] == first_due
    assert all(before < after for before, after in zip(dates, dates[1:], strict=False))
    for index, due in enumerate(dates[1:], start=1):
        assert month_number(due) - month_number(first_due) == index
        assert due.day == min(payment_day, calendar.monthrange(due.year, due.month)[1])


# --- Plan-Länge bei aus der Laufzeit abgeleiteter Rate/Tilgung ------------------------------------
#
# `derived_plan` baut den Plan wie der Service: Rate bzw. Tilgung aus der Laufzeit abgeleitet,
# das Laufzeitende (Fälligkeit der letzten planmäßigen Rate) als `final_due`.


def derived_plan(
    remaining: Decimal, percent: Decimal, term: int, *, annuity: bool, with_final_due: bool
) -> list[PlannedInstallment]:
    try:
        installment, fixed_principal = installments_for_term(remaining, percent, term, annuity=annuity)
    except ScheduleError as error:
        # Winzige Beträge mit sehr langer Laufzeit: Laufzeit nicht erreichbar (eigener Test)
        assert error.code == "term_unreachable"
        assume(False)
    final_due = add_months(FIRST_DUE, term - 1, PAYMENT_DAY) if with_final_due else None
    return build_plan(
        remaining=remaining,
        annual_percent=percent,
        first_due=FIRST_DUE,
        payment_day=PAYMENT_DAY,
        installment=installment,
        fixed_principal=fixed_principal,
        final_due=final_due,
    )


# Bewiesen für Restschuld >= 100 €, Zins <= 15 %, Laufzeit <= 60 Monate (5 Jahre):
#  - Tilgung: term · aufgerundete Tilgung >= Restschuld und (term − 1) · Tilgung < Restschuld, solange
#    Restschuld >= 0,01 · term · (term − 1) (für term <= 60 mindestens 35,40 €).
#  - Annuität: Der Rundungsfehler der Zinsen (je Rate <= 0,005 €) und der aufgerundeten Rate
#    (< 0,01 €) wirkt höchstens mit 0,015 · ((1+q)^(term−1) − 1)/q <= 1,30 € auf die Restschuld vor
#    der letzten Rate (mindestens 1,64 €); ein verbleibender Rest ist höchstens 0,005 · ((1+q)^term −
#    1)/q <= 0,45 € und damit unter der Toleranz von 1,00 €, `final_due` übernimmt ihn.
@PLAN_PROPERTY
@given(
    remaining=REMAINING,
    percent=ANNUAL_PERCENT,
    term=st.integers(min_value=1, max_value=60),
    annuity=st.booleans(),
)
def test_derived_plan_has_exactly_term_installments_for_terms_up_to_five_years(
    remaining, percent, term, annuity
):
    plan = derived_plan(remaining, percent, term, annuity=annuity, with_final_due=True)
    assert len(plan) == term
    check_term_matches(plan, term)


@PLAN_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT, term=TERM)
def test_derived_fixed_principal_plan_is_never_longer_than_the_term(remaining, percent, term):
    # term · aufgerundete Tilgung >= Restschuld, also reichen höchstens `term` Raten
    plan = build_plan(
        remaining=remaining,
        annual_percent=percent,
        first_due=FIRST_DUE,
        payment_day=PAYMENT_DAY,
        fixed_principal=fixed_principal_for(remaining, term),
    )
    assert len(plan) <= term


# Ohne Laufzeitende kann eine feste (aufgerundete) Rate einen Rundungsrest als Mini-Rate
# hinterlassen (10.000 €/5 %/3 Monate: nach Rate 3 bleiben 0,01 €). Das ist gewollt – bei
# vereinbarter Laufzeit übergibt der Service immer `final_due`, dann gibt es keine Mini-Rate.


@PLAN_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT, term=TERM_AT_LEAST_TWO)
@example(remaining=D("100.07"), percent=D("15"), term=400)
def test_derived_annuity_plan_with_final_due_is_never_longer_than_the_term(
    remaining, percent, term
):
    plan = derived_plan(remaining, percent, term, annuity=True, with_final_due=True)
    assert len(plan) <= term


@PLAN_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT, term=TERM_AT_LEAST_TWO)
@example(remaining=D("100.00"), percent=D("0"), term=101)
@example(remaining=D("100.00"), percent=D("15"), term=102)
def test_derived_annuity_plan_has_exactly_term_installments(remaining, percent, term):
    plan = derived_plan(remaining, percent, term, annuity=True, with_final_due=True)
    assert len(plan) == term


@PLAN_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT, term=TERM_AT_LEAST_TWO)
@example(remaining=D("100.00"), percent=D("0"), term=101)
def test_derived_fixed_principal_plan_has_exactly_term_installments(remaining, percent, term):
    plan = derived_plan(remaining, percent, term, annuity=False, with_final_due=True)
    assert len(plan) == term


@PLAN_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT, term=TERM)
@example(remaining=D("100.40"), percent=D("15"), term=446)
@example(remaining=D("100.00"), percent=D("0"), term=101)
def test_derived_installment_amortizes_or_term_is_unreachable(remaining, percent, term):
    # 100,40 €/15 %/446 Monate: exakte Rate 1,259945…, erste Zinsen 1,255 → 1,26 – selbst die
    # kleinste tilgende Rate (1,27) tilgt vor Laufzeitende → term_unreachable statt never_amortizes
    try:
        installment, _ = installments_for_term(remaining, percent, term, annuity=True)
    except ScheduleError as error:
        assert error.code == "term_unreachable"
        return
    assert installment > monthly_interest(remaining, percent)


def test_installments_for_term_lowers_a_rounded_up_amount_to_reach_the_term():
    # 100 €/0 %/101 Monate: aufgerundet 1,00 → nur 100 Raten; 0,99 → 100 · 0,99 + Schlussrate 1,00
    assert installments_for_term(D("100.00"), D("0"), 101, annuity=False) == (None, D("0.99"))
    assert installments_for_term(D("100.00"), D("0"), 101, annuity=True) == (D("0.99"), None)
    plan = build_plan(
        remaining=D("100.00"), annual_percent=D("0"), first_due=FIRST_DUE, payment_day=PAYMENT_DAY,
        fixed_principal=D("0.99"), final_due=add_months(FIRST_DUE, 100, PAYMENT_DAY),
    )
    assert len(plan) == 101 and plan[-1].principal == D("1.00")


def test_term_unreachable_for_a_tiny_long_loan():
    with pytest.raises(ScheduleError) as caught:
        installments_for_term(D("100.40"), D("15"), 446, annuity=True)
    assert caught.value.code == "term_unreachable"


def test_user_installment_far_below_the_term_is_inconsistent():
    # Rate 200,00 statt 230,30 für 48 Monate: die Schlussrate läge weit über der Rate
    plan = reference_plan(installment=D("200.00"), final_due=LAST_DUE)
    assert len(plan) == 48
    with pytest.raises(ScheduleError) as caught:
        check_term_matches(plan, 48, D("200.00"))
    assert caught.value.code == "loan_terms_inconsistent"
    # die kaufmännisch gerundete Bankrate passt dagegen (Schlussrate 230,48)
    check_term_matches(reference_plan(installment=D("230.29"), final_due=LAST_DUE), 48, D("230.29"))


# --- Gegenprobe der Formeln mit ganzzahliger Cent-Rechnung ----------------------------------------
#
# Monatszins q = p / 1200 = u / 12.000.000 mit u = p in Zehntausendstel Prozent (5 % → u = 50.000).

MONTH_BASE = 12_000_000


def cents(amount: Decimal) -> int:
    return int(amount.scaleb(2))


def euro(amount_in_cents: int) -> Decimal:
    return D(amount_in_cents).scaleb(-2)


def ten_thousandths(percent: Decimal) -> int:
    return int(percent.scaleb(4))


def exact_monthly_interest_cents(remaining: Decimal, percent: Decimal) -> tuple[int, bool]:
    """(Zinsen in Cent kaufmännisch gerundet, exakter Wert liegt auf einem halben Cent)."""
    numerator = cents(remaining) * ten_thousandths(percent)
    return (numerator + MONTH_BASE // 2) // MONTH_BASE, numerator % MONTH_BASE == MONTH_BASE // 2


def exact_annuity_cents(remaining: Decimal, percent: Decimal, term: int) -> tuple[int, bool]:
    """(aufgerundete Annuität in Cent, exakter Wert liegt genau auf einem Cent).

    A = K · q · (1+q)^n / ((1+q)^n − 1) mit q = u/b und (1+q)^n = (b+u)^n / b^n.
    """
    capital, units = cents(remaining), ten_thousandths(percent)
    if units == 0:
        numerator, denominator = capital, term
    else:
        growth = (MONTH_BASE + units) ** term
        numerator = capital * units * growth
        denominator = MONTH_BASE * (growth - MONTH_BASE**term)
    return -(-numerator // denominator), numerator % denominator == 0


def exact_accrued_cents(remaining: Decimal, percent: Decimal, days: int) -> int:
    """Kaufmännisch gerundet: K · p/100 · Tage/365, p in Zehntausendstel als ganze Zahl."""
    numerator = cents(remaining) * ten_thousandths(percent) * days
    denominator = 1_000_000 * 365
    return (2 * numerator + denominator) // (2 * denominator)


@CHEAP_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT)
def test_monthly_interest_matches_exact_integer_arithmetic(remaining, percent):
    expected, on_half_cent = exact_monthly_interest_cents(remaining, percent)
    # exakte Halbcent-Werte: siehe test_monthly_interest_rounds_exact_half_cents_up
    assume(not on_half_cent)
    result = monthly_interest(remaining, percent)
    assert result == euro(expected)
    assert result.as_tuple().exponent == -2


@CHEAP_PROPERTY
@given(remaining=REMAINING, percent=ANNUAL_PERCENT, term=TERM)
def test_annuity_installment_matches_exact_integer_arithmetic(remaining, percent, term):
    expected, on_whole_cent = exact_annuity_cents(remaining, percent, term)
    # Annuität mit Zins, die exakt auf einem Cent liegt: siehe
    # test_annuity_installment_does_not_round_up_an_exact_cent_amount
    assume(percent == 0 or not on_whole_cent)
    result = annuity_installment(remaining, percent, term)
    assert result == euro(expected)
    assert result.as_tuple().exponent == -2


@CHEAP_PROPERTY
@given(remaining=REMAINING, term=TERM)
def test_fixed_principal_for_rounds_the_exact_quotient_up(remaining, term):
    result = fixed_principal_for(remaining, term)
    assert result == euro(-(-cents(remaining) // term))
    assert result.as_tuple().exponent == -2


@CHEAP_PROPERTY
@given(
    remaining=REMAINING,
    percent=ANNUAL_PERCENT,
    days=st.integers(min_value=-10, max_value=4000),
)
def test_accrued_interest_matches_exact_integer_arithmetic(remaining, percent, days):
    expected = exact_accrued_cents(remaining, percent, days) if days > 0 else 0
    result = accrued_interest(remaining, percent, days)
    assert result == euro(expected)
    assert result.as_tuple().exponent == -2


AMOUNTS = st.decimals(min_value=D("0.00"), max_value=D("2000.00"), places=2)
DUES = st.decimals(min_value=D("0.00"), max_value=D("1000.00"), places=2)


@CHEAP_PROPERTY
@given(amount=AMOUNTS, interest_due=DUES, extra_due=DUES)
def test_split_payment_properties(amount, interest_due, extra_due):
    interest, principal, extra = split_payment(amount, interest_due=interest_due, extra_due=extra_due)
    assert interest + principal + extra == amount
    assert 0 <= extra <= extra_due
    assert 0 <= interest <= interest_due
    assert principal >= 0
    if amount >= extra_due + interest_due:
        # alles gedeckt: der Rest geht in die Tilgung
        assert (extra, interest) == (extra_due, interest_due)
    else:
        assert principal == 0
    if interest > 0:
        assert extra == extra_due  # zuerst die Gebühren
