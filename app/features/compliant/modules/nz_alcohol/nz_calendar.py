"""Working days as the Sale and Supply of Alcohol Act 2012 counts them (s 5).

A working day is any day except a Saturday or Sunday; Waitangi Day, Good Friday, Easter
Monday, Anzac Day, the Sovereign's birthday, Matariki and Labour Day; the Monday after
Waitangi Day or Anzac Day when either falls on a weekend; and any day from 20 December
to 15 January. Regional anniversary days aren't excluded.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# Te Kāhui o Matariki Public Holiday Act 2022, Schedule 1.
MATARIKI = {
    2022: date(2022, 6, 24),
    2023: date(2023, 7, 14),
    2024: date(2024, 6, 28),
    2025: date(2025, 6, 20),
    2026: date(2026, 7, 10),
    2027: date(2027, 6, 25),
    2028: date(2028, 7, 14),
    2029: date(2029, 7, 6),
    2030: date(2030, 6, 21),
    2031: date(2031, 7, 11),
    2032: date(2032, 7, 2),
    2033: date(2033, 6, 24),
    2034: date(2034, 7, 7),
    2035: date(2035, 6, 29),
}


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_monday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def _mondayised(day: date) -> date:
    return day + timedelta(days=7 - day.weekday()) if day.weekday() >= 5 else day


@lru_cache(maxsize=64)
def non_working_days(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    days = {
        date(year, 2, 6),
        _mondayised(date(year, 2, 6)),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 4, 25),
        _mondayised(date(year, 4, 25)),
        _nth_monday(year, 6, 1),  # Sovereign's birthday
        _nth_monday(year, 10, 4),  # Labour Day
    }
    if year in MATARIKI:
        days.add(MATARIKI[year])
    return frozenset(days)


def is_working_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    if (day.month == 12 and day.day >= 20) or (day.month == 1 and day.day <= 15):
        return False
    return day not in non_working_days(day.year)


def working_days_before(day: date, n: int) -> date:
    """The latest date that is at least ``n`` working days before ``day``.

    Counting as the Act does: the n working days between the date and ``day`` don't
    include either end.
    """
    count = 0
    current = day
    while count < n:
        current -= timedelta(days=1)
        if is_working_day(current):
            count += 1
    # step back to the previous working day: that's the last day to file
    current -= timedelta(days=1)
    while not is_working_day(current):
        current -= timedelta(days=1)
    return current
