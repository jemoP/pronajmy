"""Platby nájmu a jistota (P06, P07). Peníze jsou vždy pohyby (money.Entry); pronájmy je
zakládají přes službu pohybů (s účelem podle kódu a bytem smlouvy), nebo na ně jen odkazují."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, QuerySet, Sum

from apps.core.formatting import format_czk
from apps.money.models import Category, CategoryCode, Entry, EntryKind
from apps.money.services.entries import EntryInput, create_entry
from apps.rentals.models import ChargeKind, Lease, PaymentKind, RentPayment
from apps.rentals.services.charges import ensure_charges, lease_balance, tracking_start
from apps.rentals.services.leases import end_lease, lease_end, tenant_names

CHARGE_CATEGORY: dict[str, CategoryCode] = {
    ChargeKind.RENT: CategoryCode.RENT,
    ChargeKind.SERVICES: CategoryCode.SERVICES,
    ChargeKind.SETTLEMENT: CategoryCode.SETTLEMENT,
    ChargeKind.OTHER: CategoryCode.OTHER_INCOME,
}
INCOME_KINDS = (PaymentKind.PAYMENT, PaymentKind.DEPOSIT)
EXPENSE_KINDS = (PaymentKind.REFUND, PaymentKind.DEPOSIT_RETURN)
SUGGEST_DAYS = 45  # návrhy pohybů do tolika dní před začátkem / po konci nájmu


def category_id(code: CategoryCode) -> int:
    """Výchozí účel podle kódu (ZM-002) – funguje i po přejmenování."""
    return Category.objects.only("id").get(code=code).id


def payment_note(lease: Lease, label: str) -> str:
    parts = [label, tenant_names(lease)]
    if lease.variable_symbol:
        parts.append(f"VS {lease.variable_symbol}")
    return " – ".join(p for p in parts if p)


def _entry(
    lease: Lease,
    *,
    day: date,
    kind: EntryKind,
    amount: int,
    account_id: int,
    code: CategoryCode,
    note: str,
) -> Entry:
    return create_entry(
        EntryInput(
            date=day,
            kind=kind,
            amount_cents=amount,
            account_id=account_id,
            category_id=category_id(code),
            property_id=lease.property_id,
            note=note,
        )
    )


def allocate(lease: Lease, amount: int, today: date) -> dict[CategoryCode, int]:
    """Rozdělí platbu podle otevřených předpisů (FIFO) na účely; přeplatek = nájemné."""
    ensure_charges(lease, today)
    split: dict[CategoryCode, int] = {}
    rest = amount
    for state in lease_balance(lease, today).charges:
        if rest <= 0:
            break
        if state.open_cents <= 0:
            continue
        part = min(rest, state.open_cents)
        code = CHARGE_CATEGORY.get(state.charge.kind, CategoryCode.OTHER_INCOME)
        split[code] = split.get(code, 0) + part
        rest -= part
    if rest > 0:
        split[CategoryCode.RENT] = split.get(CategoryCode.RENT, 0) + rest
    return split


@transaction.atomic
def record_payment(
    lease: Lease,
    *,
    day: date,
    amount: int,
    account_id: int,
    deposit_amount: int = 0,
    note: str = "",
    today: date,
) -> list[Entry]:
    """Zapíše přijatou platbu: příjmy podle předpisů (nájemné, zálohy…) + případnou jistotu."""
    if amount < 0 or deposit_amount < 0 or amount + deposit_amount <= 0:
        raise ValidationError({"amount": "Částka musí být větší než 0."})
    created: list[Entry] = []
    label = note.strip()
    if amount:
        for code, part in allocate(lease, amount, today).items():
            entry = _entry(
                lease,
                day=day,
                kind=EntryKind.INCOME,
                amount=part,
                account_id=account_id,
                code=code,
                note=payment_note(lease, label or code.label),
            )
            RentPayment.objects.create(
                lease=lease, entry=entry, kind=PaymentKind.PAYMENT, amount_cents=part
            )
            created.append(entry)
    if deposit_amount:
        entry = _entry(
            lease,
            day=day,
            kind=EntryKind.INCOME,
            amount=deposit_amount,
            account_id=account_id,
            code=CategoryCode.DEPOSIT,
            note=payment_note(lease, "Jistota"),
        )
        RentPayment.objects.create(
            lease=lease, entry=entry, kind=PaymentKind.DEPOSIT, amount_cents=deposit_amount
        )
        created.append(entry)
    return created


@transaction.atomic
def pay_out(
    lease: Lease,
    *,
    kind: str,
    day: date,
    amount: int,
    account_id: int,
    note: str = "",
    today: date,
) -> Entry:
    """Vrácení přeplatku (REFUND) nebo jistoty (DEPOSIT_RETURN) – náklad z účtu."""
    if kind not in EXPENSE_KINDS:
        raise ValidationError({"kind": "Neplatný druh výplaty."})
    if amount <= 0:
        raise ValidationError({"amount": "Částka musí být větší než 0."})
    if kind == PaymentKind.DEPOSIT_RETURN:
        held = lease_balance(lease, today).deposit.held
        if amount > held:
            raise ValidationError(
                {"amount": f"Vrátit jde nejvýš drženou jistotu {format_czk(held)}."}
            )
    deposit = kind == PaymentKind.DEPOSIT_RETURN
    label = "Vrácení jistoty" if deposit else "Vrácení přeplatku"
    entry = _entry(
        lease,
        day=day,
        kind=EntryKind.EXPENSE,
        amount=amount,
        account_id=account_id,
        # Vrácený přeplatek snižuje příjmy (ZM-003).
        code=CategoryCode.DEPOSIT if deposit else CategoryCode.SETTLEMENT,
        note=payment_note(lease, note.strip() or label),
    )
    RentPayment.objects.create(lease=lease, entry=entry, kind=kind, amount_cents=amount)
    return entry


@transaction.atomic
def offset_deposit(lease: Lease, *, day: date, amount: int, note: str = "") -> RentPayment:
    """Započtení jistoty na dluh – bez pohybu, sníží saldo i drženou jistotu."""
    held = lease_balance(lease, day).deposit.held
    if amount <= 0:
        raise ValidationError({"amount": "Částka musí být větší než 0."})
    if amount > held:
        raise ValidationError(
            {"amount": f"Započíst jde nejvýš drženou jistotu {format_czk(held)}."}
        )
    if day < tracking_start(lease):
        raise ValidationError({"day": "Datum je před začátkem sledování salda."})
    return RentPayment.objects.create(
        lease=lease,
        kind=PaymentKind.DEPOSIT_OFFSET,
        amount_cents=amount,
        date=day,
        note=note.strip(),
    )


def linked_cents(entry: Entry) -> int:
    return entry.rent_payments.aggregate(total=Sum("amount_cents"))["total"] or 0


@transaction.atomic
def link_entry(lease: Lease, entry: Entry, kind: str, amount: int | None = None) -> RentPayment:
    """Přiřadí existující pohyb (nebo jeho část) ke smlouvě. Pohyb se nemění."""
    entry = Entry.objects.select_for_update().get(pk=entry.pk)
    if kind not in INCOME_KINDS + EXPENSE_KINDS:
        raise ValidationError({"kind": "Neplatný druh platby."})
    if kind in INCOME_KINDS and entry.kind != EntryKind.INCOME:
        raise ValidationError({"entry": "Platbu nájemníka jde přiřadit jen k příjmu."})
    if kind in EXPENSE_KINDS and entry.kind != EntryKind.EXPENSE:
        raise ValidationError({"entry": "Vrácení jde přiřadit jen k nákladu."})
    if entry.property_id is not None and entry.property_id != lease.property_id:
        raise ValidationError({"entry": "Pohyb patří k jinému bytu."})
    free = entry.amount_cents - linked_cents(entry)
    amount = free if amount is None else amount
    if amount <= 0 or amount > free:
        raise ValidationError({"amount": f"Z pohybu zbývá k přiřazení {format_czk(max(free, 0))}."})
    return RentPayment.objects.create(lease=lease, entry=entry, kind=kind, amount_cents=amount)


def unlinked_income(lease: Lease) -> QuerySet[Entry]:
    """Příjmy bez (úplného) přiřazení ke smlouvě v okolí doby nájmu."""
    start = tracking_start(lease) - timedelta(days=SUGGEST_DAYS)
    end = lease_end(lease)
    qs = Entry.objects.filter(kind=EntryKind.INCOME, date__gte=start)
    if end:
        qs = qs.filter(date__lte=end + timedelta(days=SUGGEST_DAYS))
    return qs.annotate(linked=Sum("rent_payments__amount_cents")).filter(
        Q(linked__isnull=True) | Q(linked__lt=F("amount_cents"))
    )


@dataclass(frozen=True)
class Suggestion:
    entry: Entry
    free_cents: int


def suggestions(lease: Lease, today: date, limit: int = 15) -> list[Suggestion]:
    """Nepřiřazené příjmy bytu nebo příjmy bez bytu na účet smlouvy,
    nejbližší měsíční platbě nahoře."""
    scope = Q(property_id=lease.property_id)
    if lease.account_id:
        scope |= Q(account_id=lease.account_id, property__isnull=True)
    rows = (
        unlinked_income(lease)
        .filter(scope)
        .select_related("category", "account")
        .order_by("-date")[:200]
    )
    monthly = lease.rent_cents + lease.services_cents
    ranked = sorted(rows, key=lambda e: (abs(e.amount_cents - monthly), -e.date.toordinal()))
    return [Suggestion(e, e.amount_cents - (e.linked or 0)) for e in ranked[:limit]]  # type: ignore[attr-defined]


def unlink(payment: RentPayment) -> None:
    """Odebere vazbu (pohyb zůstává)."""
    payment.delete()


@transaction.atomic
def end_with_settlement(
    lease: Lease, terminated_on: date, reason: str, *, today: date, confirm: bool
) -> Lease:
    """Ukončí smlouvu; s nevyrovnaným saldem nebo drženou jistotou jen s potvrzením."""
    end_lease(lease, terminated_on, reason)
    ensure_charges(lease, today)
    balance = lease_balance(lease, today)
    if not confirm and (balance.balance or balance.deposit.held):
        raise ValidationError(
            {
                "confirm": f"Saldo je {format_czk(balance.balance)} a držená jistota"
                f" {format_czk(balance.deposit.held)} – vypořádej je, nebo ukončení potvrď."
            }
        )
    return lease
