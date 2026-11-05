"""Bankarbeitstage in Deutschland: Wochenende und bundesweite Feiertage (TARGET-ähnlich vereinfacht).

Regionale Feiertage fehlen bewusst – für die Toleranz bei erwarteten Zahlungen reicht das.
"""

from datetime import date, timedelta
from functools import lru_cache


def easter(year: int) -> date:
    """Ostersonntag (Gaußsche Osterformel, gregorianisch)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    sunday = easter(year)
    return frozenset({
        date(year, 1, 1), sunday - timedelta(days=2), sunday + timedelta(days=1), date(year, 5, 1),
        sunday + timedelta(days=39), sunday + timedelta(days=50), date(year, 10, 3),
        date(year, 12, 24), date(year, 12, 25), date(year, 12, 26), date(year, 12, 31),
    })


def is_holiday(day: date) -> bool:
    return day in holidays(day.year)


def is_business_day(day: date) -> bool:
    return day.weekday() < 5 and not is_holiday(day)


def next_business_day(day: date) -> date:
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def add_business_days(day: date, count: int) -> date:
    while count > 0:
        day += timedelta(days=1)
        if is_business_day(day):
            count -= 1
    return day
