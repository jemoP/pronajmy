"""Výkaz pronájmů (P12) a podklad pro daňové přiznání (P13).

Počítá stejně jako výsledek v pohybech: příjmy a náklady s účelem druhu příjem / náklad do
dneška včetně; náklad s účelem druhu příjem (vrácení příjmu, ZM-003) snižuje příjmy svého
účelu. Jistota (neutrální účel), převody, výběry a vklady se nepočítají. Do podkladu pro daně
patří jen účely s příznakem taxable (ZM-004). Výsledek se dělí na nájem a služby podle
příznaku účelu is_service (ZM-008); celkem = nájem + služby.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from django.db.models import QuerySet, Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from apps.core.formatting import czech_sort_key
from apps.money.models import CATEGORIZED_KINDS, CategoryKind, Entry, EntryKind
from apps.money.services.accounts import balances_at
from apps.rentals.models import Property

# § 9 odst. 4 ZDP: výdajový paušál 30 % z příjmů z nájmu, nejvýš 600 000 Kč ročně.
FLAT_RATE_PERCENT = 30
FLAT_RATE_CAP = 600_000_00
NO_PROPERTY = "Bez bytu"
RENT, SERVICES = "rent", "services"  # skupiny výsledku (ZM-008)


def result_entries(date_from: date, date_to: date, today: date) -> QuerySet[Entry]:
    """Pohyby, které patří do výsledku, za období (plánované ne)."""
    return Entry.objects.filter(
        kind__in=CATEGORIZED_KINDS,
        category__kind__in=(CategoryKind.INCOME, CategoryKind.EXPENSE),
        date__gte=date_from,
        date__lte=min(date_to, today),
    )


def signed(kind: str, category_kind: str, total: int) -> tuple[str, int]:
    """(strana výkazu, částka): vrácení příjmu jde do příjmů se záporným znaménkem."""
    if category_kind == CategoryKind.INCOME:
        return "income", total if kind == EntryKind.INCOME else -total
    return "expense", total


def group_of(is_service: bool | None) -> str:
    return SERVICES if is_service else RENT


@dataclass
class GroupResult:
    """Příjmy a náklady jedné skupiny (nájem / služby) podle účelů."""

    income: dict[str, int] = field(default_factory=dict)  # účel → haléře
    expense: dict[str, int] = field(default_factory=dict)

    @property
    def income_total(self) -> int:
        return sum(self.income.values())

    @property
    def expense_total(self) -> int:
        return sum(self.expense.values())

    @property
    def result(self) -> int:
        """Nájem: zisk; služby: rozdíl (kladný = zálohy pokryly náklady)."""
        return self.income_total - self.expense_total

    def add(self, side: str, name: str, amount: int) -> None:
        target = self.income if side == "income" else self.expense
        target[name] = target.get(name, 0) + amount

    def sort(self) -> None:
        self.income = dict(sorted(self.income.items(), key=lambda i: czech_sort_key(i[0])))
        self.expense = dict(sorted(self.expense.items(), key=lambda i: czech_sort_key(i[0])))


@dataclass
class PropertyResult:
    property_id: int | None
    name: str
    rent: GroupResult = field(default_factory=GroupResult)
    services: GroupResult = field(default_factory=GroupResult)

    def group(self, name: str) -> GroupResult:
        return self.services if name == SERVICES else self.rent

    @property
    def income_total(self) -> int:
        return self.rent.income_total + self.services.income_total

    @property
    def expense_total(self) -> int:
        return self.rent.expense_total + self.services.expense_total

    @property
    def profit(self) -> int:
        return self.income_total - self.expense_total


@dataclass(frozen=True)
class TaxSummary:
    income: int  # příjmy z nájmu bez průběžných položek
    actual_expenses: int
    excluded_income: dict[str, int]  # účel → částka, nepočítá se do daní
    excluded_expense: dict[str, int]

    @property
    def flat_rate(self) -> int:
        return flat_rate(self.income)

    @property
    def actual_base(self) -> int:
        return self.income - self.actual_expenses

    @property
    def flat_base(self) -> int:
        return self.income - self.flat_rate

    @property
    def better(self) -> str:
        return "paušál" if self.flat_rate > self.actual_expenses else "skutečné výdaje"


@dataclass(frozen=True)
class AccountFlows:
    balance_end: int  # zůstatek všech účtů ke konci roku (nebo k dnešku)
    withdrawn: int  # výběry do domácnosti
    deposited: int  # vklady z domácnosti


@dataclass(frozen=True)
class YearResult:
    year: int
    rent_income: int = 0
    rent_expense: int = 0
    service_income: int = 0
    service_expense: int = 0

    @property
    def income(self) -> int:
        return self.rent_income + self.service_income

    @property
    def expense(self) -> int:
        return self.rent_expense + self.service_expense

    @property
    def profit(self) -> int:
        return self.income - self.expense

    @property
    def rent_profit(self) -> int:
        return self.rent_income - self.rent_expense

    @property
    def service_difference(self) -> int:
        return self.service_income - self.service_expense


def year_result_from(year: int, sums: dict[tuple[str, str], int]) -> YearResult:
    """YearResult z {(skupina, strana): částka}."""
    return YearResult(
        year,
        sums.get((RENT, "income"), 0),
        sums.get((RENT, "expense"), 0),
        sums.get((SERVICES, "income"), 0),
        sums.get((SERVICES, "expense"), 0),
    )


@dataclass(frozen=True)
class RentalReport:
    year: int
    properties: list[PropertyResult]
    months: list[YearResult]  # 12 měsíců (pole year = číslo měsíce)
    previous: YearResult
    tax: TaxSummary
    flows: AccountFlows

    @property
    def totals(self) -> YearResult:
        return YearResult(
            self.year,
            sum(p.rent.income_total for p in self.properties),
            sum(p.rent.expense_total for p in self.properties),
            sum(p.services.income_total for p in self.properties),
            sum(p.services.expense_total for p in self.properties),
        )

    @property
    def income(self) -> int:
        return self.totals.income

    @property
    def expense(self) -> int:
        return self.totals.expense

    @property
    def profit(self) -> int:
        return self.income - self.expense

    @property
    def months_income(self) -> list[int]:
        return [m.income for m in self.months]

    @property
    def months_expense(self) -> list[int]:
        return [m.expense for m in self.months]


def flat_rate(income: int) -> int:
    """Paušál 30 % z příjmů, nejvýš 600 000 Kč (ze záporných příjmů nic)."""
    return min(max(income, 0) * FLAT_RATE_PERCENT // 100, FLAT_RATE_CAP)


def year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def account_flows(year: int, today: date) -> AccountFlows:
    start, end = year_bounds(year)
    end = min(end, today)
    flows = (
        Entry.objects.filter(
            kind__in=(EntryKind.WITHDRAWAL, EntryKind.DEPOSIT), date__gte=start, date__lte=end
        )
        .values("kind")
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    totals = {row["kind"]: row["total"] or 0 for row in flows}
    return AccountFlows(
        balance_end=sum(balances_at(end).values()),
        withdrawn=totals.get(EntryKind.WITHDRAWAL, 0),
        deposited=totals.get(EntryKind.DEPOSIT, 0),
    )


def tax_summary(qs: QuerySet[Entry]) -> TaxSummary:
    income = expense = 0
    excluded: dict[str, dict[str, int]] = {"income": {}, "expense": {}}
    rows = (
        qs.values("kind", "category__kind", "category__name", "category__taxable")
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    for row in rows:
        side, amount = signed(row["kind"], row["category__kind"], row["total"] or 0)
        if not row["category__taxable"]:
            bucket = excluded[side]
            bucket[row["category__name"]] = bucket.get(row["category__name"], 0) + amount
        elif side == "income":
            income += amount
        else:
            expense += amount
    return TaxSummary(income, expense, excluded["income"], excluded["expense"])


GROUPED = ("kind", "category__kind", "category__is_service")


def year_result(year: int, today: date, property_id: int | None = None) -> YearResult:
    qs = result_entries(*year_bounds(year), today)
    if property_id:
        qs = qs.filter(property_id=property_id)
    sums: dict[tuple[str, str], int] = defaultdict(int)
    for row in qs.values(*GROUPED).annotate(total=Sum("amount_cents")).order_by():
        side, amount = signed(row["kind"], row["category__kind"], row["total"] or 0)
        sums[(group_of(row["category__is_service"]), side)] += amount
    return year_result_from(year, sums)


def rental_report(year: int, today: date, property_id: int | None = None) -> RentalReport:
    qs = result_entries(*year_bounds(year), today)
    if property_id:
        qs = qs.filter(property_id=property_id)
    names = {p.id: p.name for p in Property.objects.all()}
    results: dict[int | None, PropertyResult] = {}
    rows = (
        qs.values("property_id", "category__name", *GROUPED)
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    for row in rows:
        pid = row["property_id"]
        result = results.setdefault(pid, PropertyResult(pid, names.get(pid, NO_PROPERTY)))
        side, amount = signed(row["kind"], row["category__kind"], row["total"] or 0)
        result.group(group_of(row["category__is_service"])).add(side, row["category__name"], amount)

    months: list[dict[tuple[str, str], int]] = [defaultdict(int) for _ in range(12)]
    by_month = (
        qs.annotate(m=ExtractMonth("date"))
        .values("m", *GROUPED)
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    for month_row in by_month:
        total = month_row["total"] or 0
        side, amount = signed(month_row["kind"], month_row["category__kind"], total)
        months[month_row["m"] - 1][(group_of(month_row["category__is_service"]), side)] += amount

    ordered = sorted(
        results.values(), key=lambda r: (r.property_id is None, czech_sort_key(r.name))
    )
    for result in ordered:
        result.rent.sort()
        result.services.sort()
    return RentalReport(
        year=year,
        properties=ordered,
        months=[year_result_from(m + 1, months[m]) for m in range(12)],
        previous=year_result(year - 1, today, property_id),
        tax=tax_summary(qs),
        flows=account_flows(year, today),
    )


def years_overview(today: date, property_id: int | None = None) -> list[YearResult]:
    """Výsledek po letech (nejnovější nahoře), jen roky s pohyby."""
    qs = result_entries(date.min, date.max, today)
    if property_id:
        qs = qs.filter(property_id=property_id)
    sums: dict[int, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    rows = (
        qs.annotate(y=ExtractYear("date"))
        .values("y", *GROUPED)
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    for row in rows:
        side, amount = signed(row["kind"], row["category__kind"], row["total"] or 0)
        sums[row["y"]][(group_of(row["category__is_service"]), side)] += amount
    return [year_result_from(y, v) for y, v in sorted(sums.items(), reverse=True)]


def report_years(today: date) -> list[int]:
    years = {d.year for d in Entry.objects.dates("date", "year")}
    years.add(today.year)
    return sorted(years, reverse=True)
