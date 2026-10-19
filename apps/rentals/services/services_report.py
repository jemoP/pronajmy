"""Přehled služeb (ZM-007): náklady na energie a ostatní služby po měsících proti zálohám
na služby od nájemníků – podklad pro vyúčtování služeb.

Náklady = náklady s účelem s příznakem „služba“ (ZM-008). Zálohy = příjmy s účelem s příznakem
kromě Vyúčtování služeb (vrácené zálohy snižují). Vyúčtování = nedoplatky − vrácené přeplatky.
Jen pohyby do dneška včetně (plánované ne).
"""

from dataclasses import dataclass
from datetime import date

from django.db.models import QuerySet, Sum
from django.db.models.functions import ExtractMonth

from apps.money.models import SERVICE_CODES, Category, CategoryCode, CategoryKind, Entry, EntryKind


@dataclass(frozen=True)
class ServiceColumn:
    code: str
    name: str


@dataclass(frozen=True)
class ServiceRow:
    month: int  # 1–12, 0 = celkem
    costs: list[int]  # po sloupcích
    advances: int
    settlement: int

    @property
    def total(self) -> int:
        return sum(self.costs)

    @property
    def difference(self) -> int:
        """Kladné = zálohy (s vyúčtováním) pokrývají náklady, záporné = nedoplatek."""
        return self.advances + self.settlement - self.total


@dataclass(frozen=True)
class ServicesReport:
    year: int
    columns: list[ServiceColumn]
    months: list[ServiceRow]
    total: ServiceRow
    previous: ServiceRow  # celkem za předchozí rok


def service_columns() -> list[ServiceColumn]:
    """Sloupce = nákladové účely s příznakem „služba“ (ZM-008): nejdřív výchozí energie
    v pořadí kódů, pak ostatní podle pořadí v číselníku. Klíčem je id účelu."""
    order: dict[str, int] = {str(code): i for i, code in enumerate(SERVICE_CODES)}
    categories = Category.objects.filter(kind=CategoryKind.EXPENSE, is_service=True)
    ranked = sorted(categories, key=lambda c: (order.get(c.code or "", len(order)), c.sort, c.name))
    return [ServiceColumn(str(c.pk), c.name) for c in ranked]


def year_entries(year: int, today: date, property_id: int | None) -> QuerySet[Entry]:
    qs = Entry.objects.filter(date__gte=date(year, 1, 1), date__lte=min(date(year, 12, 31), today))
    if property_id:
        qs = qs.filter(property_id=property_id)
    return qs


def _monthly(
    year: int, today: date, property_id: int | None, columns: list[ServiceColumn]
) -> list[ServiceRow]:
    qs = year_entries(year, today, property_id)
    index = {c.code: i for i, c in enumerate(columns)}
    costs = [[0] * len(columns) for _ in range(12)]
    advances = [0] * 12
    settlement = [0] * 12
    rows = (
        qs.filter(category__is_service=True)
        .annotate(m=ExtractMonth("date"))
        .values("m", "kind", "category_id", "category__kind", "category__code")
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    for row in rows:
        month, amount = row["m"] - 1, row["total"] or 0
        signed = amount if row["kind"] == EntryKind.INCOME else -amount
        if row["category__kind"] == CategoryKind.INCOME:
            # Příjem ze služeb: vyúčtování zvlášť, ostatní (zálohy…) jako zálohy.
            if row["category__code"] == CategoryCode.SETTLEMENT:
                settlement[month] += signed
            else:
                advances[month] += signed
        elif row["kind"] == EntryKind.EXPENSE and (key := str(row["category_id"])) in index:
            costs[month][index[key]] += amount
    return [ServiceRow(m + 1, costs[m], advances[m], settlement[m]) for m in range(12)]


def summed(rows: list[ServiceRow], width: int) -> ServiceRow:
    return ServiceRow(
        0,
        [sum(r.costs[i] for r in rows) for i in range(width)],
        sum(r.advances for r in rows),
        sum(r.settlement for r in rows),
    )


def services_report(year: int, today: date, property_id: int | None = None) -> ServicesReport:
    columns = service_columns()
    months = _monthly(year, today, property_id, columns)
    previous = summed(_monthly(year - 1, today, property_id, columns), len(columns))
    return ServicesReport(year, columns, months, summed(months, len(columns)), previous)
