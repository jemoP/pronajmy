"""Pohyby (P02): filtr, součty, stránkování, výsledek, uložení s validací."""

from dataclasses import dataclass, replace
from datetime import date
from math import ceil

from django.core.exceptions import ValidationError
from django.db.models import Count, Q, QuerySet, Sum

from apps.money.models import (
    CATEGORIZED_KINDS,
    PROPERTY_OPTIONAL,
    Account,
    Category,
    CategoryKind,
    Entry,
    EntryKind,
)
from apps.rentals.models import Property

PAGE_SIZE = 50
SORT_FIELDS = {"date": "date", "amount": "amount_cents", "category": "category__name"}


@dataclass(frozen=True)
class EntryFilter:
    date_from: date | None = None
    date_to: date | None = None
    kind: str | None = None
    category_id: int | None = None
    property_id: int | None = None
    account_id: int | None = None
    text: str | None = None
    sort: str = "-date"
    page: int = 1

    @property
    def active(self) -> bool:
        return any(
            (
                self.date_from,
                self.date_to,
                self.kind,
                self.category_id,
                self.property_id,
                self.account_id,
                self.text,
            )
        )


@dataclass(frozen=True)
class Result:
    """Výsledek: jen příjmy a náklady s účelem druhu příjem / náklad."""

    income_cents: int = 0
    expense_cents: int = 0

    @property
    def profit_cents(self) -> int:
        return self.income_cents - self.expense_cents


@dataclass(frozen=True)
class EntryPage:
    rows: list[Entry]
    total_count: int
    page: int
    pages: int
    sums: dict[str, int]  # druh → součet bez plánovaných pohybů
    planned_count: int
    result: Result


def filtered(f: EntryFilter) -> QuerySet[Entry]:
    qs = Entry.objects.all()
    if f.date_from:
        qs = qs.filter(date__gte=f.date_from)
    if f.date_to:
        qs = qs.filter(date__lte=f.date_to)
    if f.kind:
        qs = qs.filter(kind=f.kind)
    if f.category_id:
        qs = qs.filter(category_id=f.category_id)
    if f.property_id:
        qs = qs.filter(property_id=f.property_id)
    if f.account_id:
        qs = qs.filter(Q(account_id=f.account_id) | Q(to_account_id=f.account_id))
    if f.text and (needle := f.text.strip()):
        # unaccent je oboustranný: „lekarna“ najde „Lékárna“.
        qs = qs.filter(note__unaccent__icontains=needle)
    return qs


def result_of(qs: QuerySet[Entry], today: date) -> Result:
    """Výsledek z pohybů do dneška včetně (plánované se nepočítají)."""
    rows = (
        qs.filter(
            date__lte=today,
            kind__in=CATEGORIZED_KINDS,
            category__kind__in=(CategoryKind.INCOME, CategoryKind.EXPENSE),
        )
        .values("kind")
        .annotate(total=Sum("amount_cents"))
        .order_by()
    )
    totals = {row["kind"]: row["total"] or 0 for row in rows}
    return Result(totals.get(EntryKind.INCOME, 0), totals.get(EntryKind.EXPENSE, 0))


def result_for(date_from: date, date_to: date, today: date) -> Result:
    return result_of(Entry.objects.filter(date__gte=date_from, date__lte=date_to), today)


def list_entries(f: EntryFilter, today: date) -> EntryPage:
    qs = filtered(f)
    total_count = qs.count()
    planned_count = qs.filter(date__gt=today).count()
    sums: dict[str, int] = {}
    for row in (
        qs.filter(date__lte=today)
        .values("kind")
        .annotate(n=Count("id"), total=Sum("amount_cents"))
        .order_by()
    ):
        sums[row["kind"]] = row["total"] or 0
    pages = max(1, ceil(total_count / PAGE_SIZE))
    page = min(max(1, f.page), pages)

    descending = f.sort.startswith("-")
    field = SORT_FIELDS.get(f.sort.lstrip("-"), "date")
    prefix = "-" if descending else ""
    rows = qs.select_related("account", "to_account", "category", "property").order_by(
        f"{prefix}{field}", f"{prefix}id"
    )[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    return EntryPage(
        list(rows), total_count, page, pages, sums, planned_count, result_of(qs, today)
    )


@dataclass(frozen=True)
class EntryInput:
    date: date
    kind: str
    amount_cents: int
    account_id: int | None
    to_account_id: int | None = None
    category_id: int | None = None
    property_id: int | None = None
    note: str = ""

    def normalized(self) -> "EntryInput":
        """Pole, která druh nepoužívá, se zahodí (náklad nemá cílový účet apod.)."""
        categorized = self.kind in CATEGORIZED_KINDS
        return replace(
            self,
            to_account_id=self.to_account_id if self.kind == EntryKind.TRANSFER else None,
            category_id=self.category_id if categorized else None,
            property_id=self.property_id if categorized else None,
            note=(self.note or "").strip(),
        )


def validate(data: EntryInput, original: Entry | None = None) -> dict[str, str]:
    """Neaktivní účet, účel nebo byt jde ponechat u upravovaného pohybu, ne nově vybrat."""

    def changed(field: str) -> bool:
        return original is None or getattr(original, field) != getattr(data, field)

    if data.kind not in EntryKind.values:
        return {"kind": "Vyber druh pohybu."}
    errors: dict[str, str] = {}
    if data.amount_cents <= 0:
        errors["amount"] = "Částka musí být větší než 0."

    for field, message in (
        ("account_id", "Vyber účet."),
        ("to_account_id", "Vyber účet, na který peníze přichází."),
    ):
        if field == "to_account_id" and data.kind != EntryKind.TRANSFER:
            continue
        account_id = getattr(data, field)
        if account_id is None:
            errors[field] = message
        elif (account := Account.objects.filter(pk=account_id).first()) is None:
            errors[field] = "Účet neexistuje."
        elif not account.active and changed(field):
            errors[field] = f"Účet „{account.name}“ je neaktivní."
    if data.kind == EntryKind.TRANSFER and data.account_id == data.to_account_id:
        errors.setdefault("to_account_id", "Zdrojový a cílový účet musí být různé.")

    if data.kind in CATEGORIZED_KINDS:
        property_required = True
        if data.category_id is None:
            errors["category_id"] = "Vyber účel."
        elif (category := Category.objects.filter(pk=data.category_id).first()) is None:
            errors["category_id"] = "Účel neexistuje."
        else:
            property_required = category.code not in PROPERTY_OPTIONAL
            if category.kind not in (data.kind, CategoryKind.NEUTRAL):
                kind_name = CategoryKind(category.kind).label
                errors["category_id"] = f"Účel „{category.name}“ je druhu {kind_name}."
            elif not category.active and changed("category_id"):
                errors["category_id"] = f"Účel „{category.name}“ je neaktivní."

        if data.property_id is None:
            if property_required:
                errors["property_id"] = "Vyber byt (bez bytu jen ostatní příjmy a náklady)."
        elif (prop := Property.objects.filter(pk=data.property_id).first()) is None:
            errors["property_id"] = "Byt neexistuje."
        elif not prop.active and changed("property_id"):
            errors["property_id"] = f"Byt „{prop.name}“ je neaktivní."
    return errors


def _apply(entry: Entry, data: EntryInput) -> None:
    assert data.account_id is not None  # hlídá validate()
    entry.date = data.date
    entry.kind = data.kind
    entry.amount_cents = data.amount_cents
    entry.account_id = data.account_id
    entry.to_account_id = data.to_account_id
    entry.category_id = data.category_id
    entry.property_id = data.property_id
    entry.note = data.note
    entry.save()


def create_entry(data: EntryInput) -> Entry:
    data = data.normalized()
    if errors := validate(data):
        raise ValidationError(errors)
    entry = Entry()
    _apply(entry, data)
    return entry


def update_entry(entry: Entry, data: EntryInput) -> Entry:
    data = data.normalized()
    if errors := validate(data, entry):
        raise ValidationError(errors)
    _apply(entry, data)
    return entry


def delete_entry(entry: Entry) -> None:
    entry.delete()
