"""Předpisy plateb dodavatelům (ZM-006): splátky, zaplacení, změna od data, výhled.

Splátky vznikají idempotentně do aktuálního měsíce (jako předpisy nájmu). Zaplacení vytvoří
z každého řádku rozpisu náklad s vazbou na splátku; splátka je zaplacená, když má náklad.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet

from apps.core.dates import add_months, day_in_month
from apps.core.formatting import format_czk
from apps.money.models import (
    PROPERTY_OPTIONAL,
    Account,
    Category,
    CategoryKind,
    Entry,
    EntryKind,
    Payable,
    PayableDue,
    PayableItem,
)
from apps.money.services.entries import EntryInput, create_entry
from apps.rentals.models import Property

ENDING_DAYS = 60  # upozornit na konec předpisu tolik dní předem
AUTO_ENDED_DAYS = 30  # po konci automatického předpisu připomenout zrušení příkazu


def month_start(day: date) -> date:
    return day.replace(day=1)


def wanted_dues(payable: Payable, today: date) -> dict[date, date]:
    """Období → splatnost; do aktuálního měsíce, splatnost v platnosti předpisu."""
    last = month_start(today)
    end = payable.valid_to or date.max
    result: dict[date, date] = {}
    period = month_start(payable.valid_from)
    while period <= last and period <= end:
        due = day_in_month(period, payable.due_day)
        if payable.valid_from <= due <= end:
            result[period] = due
        period = add_months(period, payable.frequency_months)
    return result


def future_dues(payable: Payable, today: date, months: int) -> list[tuple[date, date]]:
    """(období, splatnost) po aktuálním měsíci až `months` měsíců dopředu – jen výhled."""
    horizon = add_months(month_start(today), months)
    end = payable.valid_to or date.max
    rows: list[tuple[date, date]] = []
    period = month_start(payable.valid_from)
    while period <= horizon and period <= end:
        due = day_in_month(period, payable.due_day)
        if period > month_start(today) and payable.valid_from <= due <= end:
            rows.append((period, due))
        period = add_months(period, payable.frequency_months)
    return rows


@transaction.atomic
def ensure_dues(today: date) -> None:
    """Doplní splátky všech předpisů; nezaplacené mimo platnost smaže, splatnost přepočítá.
    Automatické předpisy pak k datu splatnosti zaplatí."""
    payables = Payable.objects.filter(valid_from__lte=add_months(month_start(today), 1))
    dues = PayableDue.objects.annotate(entry_count=Count("entries"))
    for payable in payables.prefetch_related(Prefetch("dues", queryset=dues)):
        wanted = wanted_dues(payable, today)
        existing = {d.period: d for d in payable.dues.all()}
        for period, due in existing.items():
            if due.entry_count:  # type: ignore[attr-defined]
                continue
            if period not in wanted:
                due.delete()
            elif due.due_date != wanted[period]:
                due.due_date = wanted[period]
                due.save(update_fields=["due_date"])
        PayableDue.objects.bulk_create(
            PayableDue(payable=payable, period=period, due_date=due_date)
            for period, due_date in wanted.items()
            if period not in existing
        )
    auto_pay(today)


def auto_pay(today: date) -> None:
    """Automatické předpisy: otevřené splátky se splatností do dneška zaplatí. Když zápis
    selže (neaktivní účet, byt…), splátka zůstane otevřená a ukáže se v upozorněních."""
    for due in open_dues(today).filter(payable__auto=True, due_date__lte=today):
        try:
            pay_dues([due.pk], day=None, today=today)
        except ValidationError:
            continue


def open_dues(today: date, property_id: int | None = None) -> QuerySet[PayableDue]:
    """Nezaplacené a nepřeskočené splátky do aktuálního měsíce, nejstarší nahoře."""
    qs = (
        PayableDue.objects.filter(skipped=False, entries__isnull=True, period__lte=today)
        .select_related("payable")
        .prefetch_related("payable__items__category", "payable__items__property")
        .order_by("due_date", "payable__name", "id")
    )
    if property_id:
        qs = qs.filter(payable__items__property_id=property_id).distinct()
    return qs


def due_amount(due: PayableDue) -> int:
    if due.amount_cents is not None:
        return due.amount_cents
    return sum(item.amount_cents for item in due.payable.items.all())


def due_label(due: PayableDue) -> str:
    return f"{due.payable.name} {due.period.month}/{due.period.year}"


@transaction.atomic
def pay_dues(due_ids: list[int], *, day: date | None, today: date, note: str = "") -> list[Entry]:
    """Zaplatí splátky: z každého řádku rozpisu samostatný náklad s vazbou na splátku.
    Datum = splatnost (nejpozději dnes), nebo zvolené `day`. Při chybě se nezapíše nic."""
    if not due_ids:
        raise ValidationError({"dues": "Označ aspoň jednu splátku."})
    if day is not None and day > today:
        raise ValidationError({"day": "Datum platby nemůže být v budoucnosti."})
    dues = list(
        PayableDue.objects.select_for_update()
        .filter(pk__in=due_ids)
        .select_related("payable")
        .order_by("due_date", "id")
    )
    if len(dues) != len(set(due_ids)):
        raise ValidationError({"dues": "Splátka neexistuje."})
    created: list[Entry] = []
    for due in dues:
        label = due_label(due)
        if due.skipped or due.entries.exists():
            raise ValidationError({"dues": f"Splátka {label} není k zaplacení."})
        items = list(due.payable.items.select_related("category").order_by("id"))
        if not items:
            raise ValidationError({"dues": f"Předpis {due.payable} nemá rozpis."})
        amounts = [i.amount_cents for i in items]
        if due.amount_cents is not None:
            amounts = [due.amount_cents]  # úprava jen u předpisu s jedním řádkem
        paid_on = day or min(due.due_date, today)
        for item, amount in zip(items, amounts, strict=False):
            text = f"{label} – {item.label or item.category.name}"
            entry = create_entry(
                EntryInput(
                    date=paid_on,
                    kind=EntryKind.EXPENSE,
                    amount_cents=amount,
                    account_id=due.payable.account_id,
                    category_id=item.category_id,
                    property_id=item.property_id,
                    note=f"{text} – {note.strip()}" if note.strip() else text,
                )
            )
            entry.payable_due = due
            entry.save(update_fields=["payable_due"])
            created.append(entry)
    return created


def set_skipped(due: PayableDue, skipped: bool) -> None:
    if skipped and due.entries.exists():
        raise ValidationError("Zaplacenou splátku nejde přeskočit.")
    due.skipped = skipped
    due.save(update_fields=["skipped"])


def set_due_amount(due: PayableDue, amount: int | None) -> None:
    """Jednorázová částka splátky – jen u předpisu s jedním řádkem rozpisu."""
    if due.entries.exists():
        raise ValidationError("Splátka je už zaplacená.")
    if amount is not None and due.payable.items.count() != 1:
        raise ValidationError(
            "Částku splátky jde upravit jen u předpisu s jedním řádkem – jinak uprav rozpis."
        )
    if amount is not None and amount <= 0:
        raise ValidationError("Částka musí být větší než 0.")
    due.amount_cents = amount
    due.save(update_fields=["amount_cents"])


# --- Předpis ------------------------------------------------------------------


@dataclass(frozen=True)
class ItemInput:
    category_id: int | None
    property_id: int | None
    amount_cents: int | None
    label: str = ""

    @property
    def empty(self) -> bool:
        return not (self.category_id or self.property_id or self.amount_cents or self.label)


def validate_items(items: list[ItemInput]) -> dict[str, str]:
    errors: dict[str, str] = {}
    rows = [(n, i) for n, i in enumerate(items) if not i.empty]
    if not rows:
        return {"items": "Zadej aspoň jeden řádek rozpisu (účel a částka)."}
    for n, item in rows:
        key = f"item_{n}"
        category = Category.objects.filter(pk=item.category_id or 0).first()
        if category is None:
            errors[key] = "Vyber účel."
        elif category.kind != CategoryKind.EXPENSE:
            errors[key] = f"Účel „{category.name}“ není náklad."
        elif item.property_id is None and category.code not in PROPERTY_OPTIONAL:
            errors[key] = "Vyber byt (bez bytu jen ostatní náklady)."
        if item.property_id and not Property.objects.filter(pk=item.property_id).exists():
            errors[key] = "Byt neexistuje."
        if not item.amount_cents or item.amount_cents <= 0:
            errors.setdefault(key, "Zadej částku větší než 0.")
    return errors


@transaction.atomic
def save_payable(payable: Payable, items: list[ItemInput]) -> Payable:
    """Uloží předpis (vyplněný z formuláře) a nahradí rozpis; otevřené splátky se přepočítají
    při příštím doplnění, zaplacené zůstávají."""
    errors = validate_items(items)
    account = Account.objects.filter(pk=payable.account_id or 0).first()
    if account is not None and not account.active:
        original = Payable.objects.filter(pk=payable.pk).first() if payable.pk else None
        if original is None or original.account_id != account.pk:
            errors["account"] = f"Účet „{account.name}“ je neaktivní."
    if not 1 <= payable.due_day <= 31:
        errors["due_day"] = "Zadej den 1–31."
    if payable.valid_to and payable.valid_to < payable.valid_from:
        errors["valid_to"] = "Konec platnosti nemůže být před začátkem."
    if errors:
        raise ValidationError(errors)
    payable.save()
    payable.items.all().delete()
    rows: list[PayableItem] = []
    for item in items:
        if item.empty:
            continue
        # validate_items zaručil účel i částku.
        assert item.category_id is not None and item.amount_cents is not None
        rows.append(
            PayableItem(
                payable=payable,
                category_id=item.category_id,
                property_id=item.property_id,
                amount_cents=item.amount_cents,
                label=item.label.strip(),
            )
        )
    PayableItem.objects.bulk_create(rows)
    return payable


@transaction.atomic
def change_from(payable: Payable, day: date) -> Payable:
    """Změna od data: starý předpis skončí den předem, vznikne navazující se stejným
    rozpisem (k úpravě). Nezaplacené splátky starého od toho data zmizí."""
    if day <= payable.valid_from:
        raise ValidationError({"day": "Změna musí platit až po začátku předpisu."})
    if payable.valid_to and day > payable.valid_to:
        raise ValidationError({"day": "Předpis v tomto dni už neplatí."})
    items = list(payable.items.all())
    new = Payable.objects.get(pk=payable.pk)
    new.pk = None
    new.valid_from = day
    new.previous = payable
    new.save()
    PayableItem.objects.bulk_create(
        PayableItem(
            payable=new,
            category_id=i.category_id,
            property_id=i.property_id,
            amount_cents=i.amount_cents,
            label=i.label,
        )
        for i in items
    )
    payable.valid_to = day - timedelta(days=1)
    payable.save(update_fields=["valid_to"])
    payable.dues.filter(due_date__gte=day, entries__isnull=True).delete()
    return new


def delete_payable(payable: Payable) -> None:
    if Entry.objects.filter(payable_due__payable=payable).exists():
        raise ValidationError("Předpis má zaplacené splátky – nejde smazat, ukonči jeho platnost.")
    payable.delete()


# --- Přehledy -----------------------------------------------------------------


def current_payables(today: date, include_ended: bool = False) -> QuerySet[Payable]:
    qs = Payable.objects.select_related("account").prefetch_related(
        "items__category", "items__property"
    )
    if not include_ended:
        qs = qs.filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
    return qs.order_by("name", "valid_from")


def monthly_amount(payable: Payable) -> int:
    """Průměr na měsíc (čtvrtletní platba / 3 …) – jen pro přehled."""
    total = sum(i.amount_cents for i in payable.items.all())
    return round(total / payable.frequency_months)


@dataclass
class ForecastMonth:
    month: date
    total: int = 0
    rows: list[tuple[Payable, date, int]] = field(default_factory=list)


def forecast(today: date, months: int = 12) -> list[ForecastMonth]:
    """Výhled plateb po měsících (bez splátek do aktuálního měsíce)."""
    by_month: dict[date, ForecastMonth] = {}
    for payable in current_payables(today):
        amount = sum(i.amount_cents for i in payable.items.all())
        for period, due in future_dues(payable, today, months):
            month = by_month.setdefault(period, ForecastMonth(period))
            month.total += amount
            month.rows.append((payable, due, amount))
    return [by_month[m] for m in sorted(by_month)]


@dataclass(frozen=True)
class PayableAlert:
    level: str  # "over" / "warning"
    text: str
    day: date


def payable_alerts(today: date) -> list[PayableAlert]:
    alerts: list[PayableAlert] = []
    for due in open_dues(today).filter(due_date__lt=today):
        text = (
            f"Nezaplaceno dodavateli: {due_label(due)} – {format_czk(due_amount(due))}"
            f" (splatné {due.due_date.day}. {due.due_date.month}. {due.due_date.year})."
        )
        if due.payable.auto:
            text += " Automatický zápis se nepovedl – zkontroluj účet a byty v předpisu."
        alerts.append(PayableAlert("over", text, due.due_date))
    ending = Payable.objects.filter(
        valid_to__gte=today, valid_to__lte=today + timedelta(days=ENDING_DAYS)
    )
    successors = set(
        Payable.objects.filter(previous__isnull=False).values_list("previous_id", flat=True)
    )
    for payable in ending:
        if payable.pk in successors or payable.valid_to is None:
            continue
        days = (payable.valid_to - today).days
        end = payable.valid_to
        text = f"Předpis platby {payable} končí {end.day}. {end.month}. {end.year} (za {days} dní)."
        alerts.append(PayableAlert("warning", text, end))
    ended_auto = Payable.objects.filter(
        auto=True, valid_to__lt=today, valid_to__gte=today - timedelta(days=AUTO_ENDED_DAYS)
    )
    for payable in ended_auto:
        if payable.pk in successors or payable.valid_to is None:
            continue
        end = payable.valid_to
        text = (
            f"Předpis platby {payable} skončil {end.day}. {end.month}. {end.year} –"
            f" zruš {payable.get_method_display()}, pokud ještě běží."
        )
        alerts.append(PayableAlert("warning", text, end))
    return alerts


def dues_by_payable(payable: Payable) -> list[tuple[PayableDue, int, list[Entry]]]:
    """Historie splátek předpisu: splátka, částka, vzniklé náklady (nejnovější nahoře)."""
    rows = []
    entries: dict[int, list[Entry]] = defaultdict(list)
    for entry in Entry.objects.filter(payable_due__payable=payable).order_by("id"):
        assert entry.payable_due_id is not None
        entries[entry.payable_due_id].append(entry)
    for due in payable.dues.select_related("payable").order_by("-period"):
        rows.append((due, due_amount(due), entries.get(due.pk, [])))
    return rows
