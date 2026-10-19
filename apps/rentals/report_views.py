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
    PropertyResult,
    RentalReport,
    YearResult,
    rental_report,
    report_years,
    years_overview,
)
from apps.rentals.services.services_report import ServicesReport, services_report


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
        # Graf jen nájmu – služby (průběžné položky) by porovnání zkreslily (ZM-008).
        "series": [
            series("Příjmy z nájmu", "series-1", [m.rent_income for m in result.months]),
            series("Náklady nájmu", "series-2", [m.rent_expense for m in result.months]),
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
            "month_rows": list(zip(MONTH_NAMES, result.months, strict=True)),
            "totals": result.totals,
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
    # Nájem a služby odděleně (ZM-008), na konci celkem.
    split = [
        Column("Příjmy z nájmu", "money"),
        Column("Náklady nájmu", "money"),
        Column("Zisk z nájmu", "money"),
        Column("Příjmy ze služeb", "money"),
        Column("Náklady na služby", "money"),
        Column("Rozdíl služeb", "money"),
        Column("Zisk celkem", "money"),
    ]

    def split_row(y: YearResult) -> list[object]:
        return [
            y.rent_income,
            y.rent_expense,
            y.rent_profit,
            y.service_income,
            y.service_expense,
            y.service_difference,
            y.profit,
        ]

    def property_year(p: PropertyResult) -> YearResult:
        r, s = p.rent, p.services
        return YearResult(year, r.income_total, r.expense_total, s.income_total, s.expense_total)

    summary = Table(
        f"Byty {year}",
        [Column("Byt", width=28), *split],
        [[p.name, *split_row(property_year(p))] for p in result.properties]
        + [["Celkem", *split_row(result.totals)]],
    )
    detail_rows: list[list[object]] = []
    for p in result.properties:
        for label, group in (("nájem", p.rent), ("služby", p.services)):
            detail_rows += [[p.name, label, "příjem", n, a] for n, a in group.income.items()]
            detail_rows += [[p.name, label, "náklad", n, a] for n, a in group.expense.items()]
    detail = Table(
        "Podle účelů",
        [
            Column("Byt", width=28),
            Column("Skupina", width=10),
            Column("Druh", width=10),
            Column("Účel", width=28),
            Column("Částka", "money"),
        ],
        detail_rows,
    )
    months = Table(
        "Měsíce",
        [Column("Měsíc", width=12), *split],
        [[MONTH_NAMES[i], *split_row(m)] for i, m in enumerate(result.months)],
    )
    by_year = Table(
        "Roky",
        [Column("Rok", "int"), *split],
        [[y.year, *split_row(y)] for y in years],
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


# --- Přehled služeb (ZM-007) --------------------------------------------------


def services(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    year, property_id = report_params(request)
    result = services_report(year, today, property_id)
    changes = [
        (current, previous)
        for current, previous in zip(result.total.costs, result.previous.costs, strict=True)
    ]
    return render(
        request,
        "rentals/report_services.html",
        {
            "nav": "report",
            "tab": "services",
            "report": result,
            "year": year,
            "years": report_years(today),
            "property_id": property_id,
            "properties": sorted(Property.objects.all(), key=lambda p: czech_sort_key(p.name)),
            "month_rows": list(zip(MONTH_NAMES, result.months, strict=True)),
            "changes": changes,
            "is_current_year": year == today.year,
        },
    )


def services_tables(result: ServicesReport, scope: str) -> list[Table]:
    columns = [Column("Měsíc", width=12)]
    columns += [Column(c.name, "money") for c in result.columns]
    columns += [
        Column("Náklady celkem", "money"),
        Column("Zálohy od nájemníků", "money"),
        Column("Vyúčtování", "money"),
        Column("Rozdíl", "money"),
    ]

    def row(label: object, r: object) -> list[object]:
        assert hasattr(r, "costs")
        return [label, *r.costs, r.total, r.advances, r.settlement, r.difference]  # type: ignore[attr-defined]

    rows = [row(MONTH_NAMES[r.month - 1], r) for r in result.months]
    rows.append(row("Celkem", result.total))
    rows.append(row(f"Celkem {result.year - 1}", result.previous))
    return [Table(f"Služby {result.year} {scope}"[:31], columns, rows)]


def services_export(request: HttpRequest, fmt: str) -> HttpResponse:
    """Export přehledu služeb – jen částky po měsících a účelech, bez kontaktů."""
    if fmt not in FORMATS:
        raise Http404
    today = timezone.localdate()
    year, property_id = report_params(request)
    result = services_report(year, today, property_id)
    prop = Property.objects.filter(pk=property_id).first() if property_id else None
    scope = prop.name if prop else "vše"
    return export_response(fmt, services_tables(result, scope), f"sluzby-{year}")
