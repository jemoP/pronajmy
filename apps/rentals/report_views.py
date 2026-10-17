"""Výkaz pronájmů (P12), podklad pro daňové přiznání (P13) a export výkazu (P14)."""

from typing import Any
from urllib.parse import urlencode

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.core.export import FORMATS, Column, Table, export_response
from apps.core.formatting import MONTH_NAMES, MONTH_SHORT, czech_sort_key
from apps.core.web import opt_int
from apps.rentals.models import Property
from apps.rentals.services.report import (
    FLAT_RATE_CAP,
    FLAT_RATE_PERCENT,
    RentalReport,
    YearResult,
    rental_report,
    report_years,
    years_overview,
)


def kc(cents: int) -> float:
    """Haléře → Kč pro data grafu (jen zobrazení, výpočty zůstávají v haléřích)."""
    return cents / 100


def series(name: str, color: str, values: list[int]) -> dict[str, Any]:
    """Jedna řada grafu; color je token z input.css (series-N)."""
    return {"name": name, "color": color, "values": [kc(v) for v in values]}


def report_params(request: HttpRequest) -> tuple[int, int | None]:
    today = timezone.localdate()
    year = opt_int(request.GET.get("year")) or today.year
    year = year if year in report_years(today) else today.year
    property_id = opt_int(request.GET.get("property"))
    if property_id and not Property.objects.filter(pk=property_id).exists():
        property_id = None
    return year, property_id


def entries_link(year: int, property_id: int | None, **params: str) -> str:
    query = {"date_from": f"{year}-01-01", "date_to": f"{year}-12-31", **params}
    if property_id:
        query["property"] = str(property_id)
    return f"{reverse('money:entries')}?{urlencode(query)}"


def with_previous(years: list[YearResult]) -> list[tuple[YearResult, YearResult | None]]:
    """Roky (nejnovější nahoře) s předchozím rokem pro meziroční změnu."""
    by_year = {y.year: y for y in years}
    return [(y, by_year.get(y.year - 1)) for y in years]


def report(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    year, property_id = report_params(request)
    result = rental_report(year, today, property_id)
    chart = {
        "type": "bar",
        "labels": MONTH_SHORT,
        "series": [
            series("Příjmy", "series-1", result.months_income),
            series("Náklady", "series-2", result.months_expense),
        ],
    }
    return render(
        request,
        "rentals/report.html",
        {
            "nav": "report",
            "report": result,
            "year": year,
            "years": report_years(today),
            "property_id": property_id,
            "properties": sorted(Property.objects.all(), key=lambda p: czech_sort_key(p.name)),
            "chart": chart,
            "month_rows": list(
                zip(MONTH_NAMES, result.months_income, result.months_expense, strict=True)
            ),
            "years_rows": with_previous(years_overview(today, property_id)),
            "flat_percent": FLAT_RATE_PERCENT,
            "flat_cap": FLAT_RATE_CAP,
            "income_link": entries_link(year, property_id, kind="INCOME"),
            "expense_link": entries_link(year, property_id, kind="EXPENSE"),
            "is_current_year": year == today.year,
        },
    )


def export_tables(result: RentalReport, years: list[YearResult]) -> list[Table]:
    """Tabulky exportu – jen byty, účely a částky (bez kontaktů a čísel účtů)."""
    year = result.year
    money = [Column("Příjmy", "money"), Column("Náklady", "money"), Column("Zisk", "money")]
    summary = Table(
        f"Byty {year}",
        [Column("Byt", width=28), *money],
        [[p.name, p.income_total, p.expense_total, p.profit] for p in result.properties]
        + [["Celkem", result.income, result.expense, result.profit]],
    )
    detail_rows: list[list[object]] = []
    for p in result.properties:
        detail_rows += [[p.name, "příjem", name, amount] for name, amount in p.income.items()]
        detail_rows += [[p.name, "náklad", name, amount] for name, amount in p.expense.items()]
    detail = Table(
        "Podle účelů",
        [
            Column("Byt", width=28),
            Column("Druh", width=10),
            Column("Účel", width=28),
            Column("Částka", "money"),
        ],
        detail_rows,
    )
    months = Table(
        "Měsíce",
        [Column("Měsíc", width=12), *money],
        [
            [
                MONTH_NAMES[i],
                result.months_income[i],
                result.months_expense[i],
                result.months_income[i] - result.months_expense[i],
            ]
            for i in range(12)
        ],
    )
    by_year = Table(
        "Roky",
        [Column("Rok", "int"), *money],
        [[y.year, y.income, y.expense, y.profit] for y in years],
    )
    tax = result.tax
    tax_rows: list[list[object]] = [
        ["Příjmy z nájmu (§ 9) – bez průběžných položek", tax.income],
        ["Skutečné výdaje podle evidence (bez odpisů a úroků)", tax.actual_expenses],
        ["Základ – skutečné výdaje", tax.actual_base],
        [f"Výdajový paušál {FLAT_RATE_PERCENT} % (nejvýš 600 000 Kč)", tax.flat_rate],
        ["Základ – paušál", tax.flat_base],
    ]
    tax_rows += [[f"Nepočítá se do daní – příjem: {n}", a] for n, a in tax.excluded_income.items()]
    tax_rows += [[f"Nepočítá se do daní – výdaj: {n}", a] for n, a in tax.excluded_expense.items()]
    taxes = Table(
        "Podklad pro DP", [Column("Položka", width=52), Column("Částka", "money")], tax_rows
    )
    return [summary, detail, months, by_year, taxes]


def report_export(request: HttpRequest, fmt: str) -> HttpResponse:
    if fmt not in FORMATS:
        raise Http404
    today = timezone.localdate()
    year, property_id = report_params(request)
    result = rental_report(year, today, property_id)
    tables = export_tables(result, years_overview(today, property_id))
    return export_response(fmt, tables, f"pronajmy-{year}")
