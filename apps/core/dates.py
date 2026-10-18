"""Pomocné funkce pro měsíce a data."""

import calendar
from datetime import date


def add_months(day: date, months: int) -> date:
    """Stejný den o N měsíců později; neexistující den → poslední den měsíce."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def day_in_month(month: date, day: int) -> date:
    """Den v měsíci; u kratšího měsíce poslední den (splatnost 31. → 28. 2.)."""
    return month.replace(day=min(day, calendar.monthrange(month.year, month.month)[1]))
