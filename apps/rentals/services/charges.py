"""Předpisy a saldo smlouvy (P06, P07).

Předpisy RENT a SERVICES se doplňují do aktuálního měsíce z podmínek platných k 1. dni
měsíce (u neúplného měsíce k začátku nájmu) a za neúplný měsíc se krátí poměrem dní na
celé Kč. Ručně upravený předpis se nepřepisuje. Platby kryjí předpisy od nejstaršího (FIFO).
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.rentals.models import (
    MONTHLY_KINDS,
    ChargeKind,
    Lease,
    LeaseStatus,
    PaymentKind,
    RentCharge,
    RentPayment,
)
from apps.rentals.services.leases import lease_end, terms_at


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def month_last(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def due_date(month: date, due_day: int) -> date:
    return month.replace(day=min(due_day, calendar.monthrange(month.year, month.month)[1]))


def tracking_start(lease: Lease) -> date:
    """Od kdy se sleduje saldo (předpisy a platby)."""
    return lease.charges_from or lease.start_date


def prorate(amount: int, month: date, start: date, end: date | None) -> int:
    """Částka za část měsíce podle dní, zaokrouhlená na celé Kč."""
    first, last = month_start(month), month_last(month)
    covered_from, covered_to = max(first, start), min(last, end or last)
    if covered_from == first and covered_to == last:
        return amount
    days = (covered_to - covered_from).days + 1
    total = (last - first).days + 1
    korun = (Decimal(amount) * days / total / 100).quantize(Decimal(1), ROUND_HALF_UP)
    return int(korun) * 100


def charge_months(lease: Lease, today: date) -> list[date]:
    """Měsíce, za které má smlouva předpis (od sledování salda do dneška / konce nájmu)."""
    if lease.status == LeaseStatus.DRAFT:
        return []
    end = lease_end(lease)
    last = month_start(min(today, end) if end else today)
    month = month_start(max(tracking_start(lease), lease.start_date))
    months = []
    while month <= last:
        months.append(month)
        month = next_month(month)
    return months


@transaction.atomic
def ensure_charges(lease: Lease, today: date) -> None:
    """Doplní a aktualizuje automatické předpisy smlouvy; ruční nechá být."""
    end = lease_end(lease)
    wanted: dict[tuple[str, date], tuple[int, date]] = {}
    for month in charge_months(lease, today):
        terms = terms_at(lease, max(month, lease.start_date))
        for kind, amount in (
            (ChargeKind.RENT, terms.rent_cents),
            (ChargeKind.SERVICES, terms.services_cents),
        ):
            value = prorate(amount, month, lease.start_date, end)
            if value > 0:
                wanted[(kind, month)] = (value, due_date(month, lease.due_day))

    existing = {
        (c.kind, c.period): c for c in lease.charges.filter(kind__in=MONTHLY_KINDS) if c.period
    }
    for key, charge in existing.items():
        if charge.manual:
            continue
        if key not in wanted:
            charge.delete()
            continue
        amount, due = wanted[key]
        if (charge.amount_cents, charge.due_date) != (amount, due):
            charge.amount_cents, charge.due_date = amount, due
            charge.save(update_fields=["amount_cents", "due_date"])
    RentCharge.objects.bulk_create(
        RentCharge(lease=lease, kind=kind, period=month, due_date=due, amount_cents=amount)
        for (kind, month), (amount, due) in wanted.items()
        if (kind, month) not in existing
    )
    _ensure_deposit_charge(lease)


def _ensure_deposit_charge(lease: Lease) -> None:
    """Předpis jistoty, pokud se saldo sleduje od začátku nájmu."""
    charge = lease.charges.filter(kind=ChargeKind.DEPOSIT, manual=False).first()
    wanted = (
        lease.status != LeaseStatus.DRAFT
        and lease.deposit_cents > 0
        and tracking_start(lease) <= lease.start_date
    )
    if not wanted:
        if charge:
            charge.delete()
        return
    due = lease.signed_date or lease.start_date
    if charge is None:
        RentCharge.objects.create(
            lease=lease, kind=ChargeKind.DEPOSIT, due_date=due, amount_cents=lease.deposit_cents
        )
    elif (charge.amount_cents, charge.due_date) != (lease.deposit_cents, due):
        charge.amount_cents, charge.due_date = lease.deposit_cents, due
        charge.save(update_fields=["amount_cents", "due_date"])


def ensure_all_charges(today: date) -> None:
    leases = Lease.objects.exclude(status=LeaseStatus.DRAFT).prefetch_related("amendments")
    for lease in leases:
        ensure_charges(lease, today)


@dataclass(frozen=True)
class ChargeState:
    charge: RentCharge
    open_cents: int  # nezaplacená část (u dobropisu 0)
    overdue: bool
    paid_by: tuple[RentPayment, ...] = ()  # platby s vazbou na tento předpis (ZM-005)


@dataclass(frozen=True)
class DepositState:
    required: int
    received: int
    returned: int
    offset: int

    @property
    def held(self) -> int:
        """Jistota, kterou pronajímatel drží."""
        return self.received - self.returned - self.offset

    @property
    def missing(self) -> int:
        return max(0, self.required - self.received)


@dataclass(frozen=True)
class LeaseBalance:
    charged: int
    paid: int  # platby + započtení − vrácené přeplatky
    overdue: int
    oldest_overdue: date | None
    charges: list[ChargeState] = field(default_factory=list)
    deposit: DepositState = DepositState(0, 0, 0, 0)
    deposit_charges: list[ChargeState] = field(default_factory=list)  # jen pro zobrazení

    @property
    def balance(self) -> int:
        """Kladné = dluh nájemce, záporné = přeplatek."""
        return self.charged - self.paid


def counted(payment: RentPayment, start: date) -> bool:
    """Do salda patří platby od začátku sledování."""
    paid_on = payment.paid_on
    return paid_on is not None and paid_on >= start


def lease_balance(lease: Lease, today: date) -> LeaseBalance:
    """Saldo z uložených předpisů a plateb (předpisy doplní ensure_charges)."""
    start = tracking_start(lease)
    charges = sorted(lease.charges.all(), key=lambda c: (c.due_date, c.kind != "RENT", c.id))
    payments = [p for p in lease.payments.all() if counted(p, start)]

    def total(*kinds: str) -> int:
        return sum(p.amount_cents for p in payments if p.kind in kinds)

    paid = total(PaymentKind.PAYMENT, PaymentKind.DEPOSIT_OFFSET) - total(PaymentKind.REFUND)
    regular = [c for c in charges if c.kind != ChargeKind.DEPOSIT]
    by_charge: dict[int, list[RentPayment]] = defaultdict(list)
    for payment in payments:
        if payment.charge_id is not None:
            by_charge[payment.charge_id].append(payment)
    # Platba s vazbou kryje nejdřív svůj předpis (ZM-005); přebytek a platby bez vazby
    # spolu se zápornými předpisy kryjí zbytek od nejstarší splatnosti (FIFO).
    direct = {
        c.id: min(
            sum(p.amount_cents for p in by_charge[c.id] if p.kind == PaymentKind.PAYMENT),
            max(c.amount_cents, 0),
        )
        for c in regular
    }
    pool = paid - sum(direct.values()) + sum(-c.amount_cents for c in regular if c.amount_cents < 0)
    states: list[ChargeState] = []
    overdue = 0
    oldest: date | None = None
    for charge in regular:
        paid_by = tuple(by_charge[charge.id])
        if charge.amount_cents <= 0:
            states.append(ChargeState(charge, 0, False, paid_by))
            continue
        rest = charge.amount_cents - direct[charge.id]
        covered = max(0, min(pool, rest))
        pool -= covered
        open_cents = rest - covered
        late = open_cents > 0 and charge.due_date < today
        if late:
            overdue += open_cents
            oldest = min(oldest, charge.due_date) if oldest else charge.due_date
        states.append(ChargeState(charge, open_cents, late, paid_by))
    deposit_pool = total(PaymentKind.DEPOSIT)
    deposit_states: list[ChargeState] = []
    for charge in (c for c in charges if c.kind == ChargeKind.DEPOSIT):
        covered = max(0, min(deposit_pool, charge.amount_cents))
        deposit_pool -= covered
        paid_by = tuple(by_charge[charge.id])
        deposit_states.append(ChargeState(charge, charge.amount_cents - covered, False, paid_by))
    deposit = DepositState(
        required=sum(c.amount_cents for c in charges if c.kind == ChargeKind.DEPOSIT),
        received=total(PaymentKind.DEPOSIT),
        returned=total(PaymentKind.DEPOSIT_RETURN),
        offset=total(PaymentKind.DEPOSIT_OFFSET),
    )
    return LeaseBalance(
        charged=sum(c.amount_cents for c in regular),
        paid=paid,
        overdue=overdue,
        oldest_overdue=oldest,
        charges=states,
        deposit=deposit,
        deposit_charges=deposit_states,
    )


BALANCE_PREFETCH = ["charges", "payments__entry", "amendments"]
