"""Hromadné mazání pohybů (ZM-009): souhrn, dopady a smazání (vše, nebo nic).

Dopady: platby nájmu navázané na pohyb se smažou (CASCADE) a saldo smlouvy vzroste; splátky
plateb dodavatelům se znovu otevřou (když zmizí všechny jejich náklady); opravy a revize přijdou
o zapsaný náklad (SET_NULL). Otisk (token) zajistí, že se maže přesně to, co bylo potvrzeno.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from apps.money.models import Entry, EntryKind, PayableDue
from apps.rentals.models import Inspection, Lease, PaymentKind, RentPayment, Repair

MAX_ENTRIES = 50  # jedna stránka seznamu


def selected(entry_ids: list[int]) -> QuerySet[Entry]:
    return (
        Entry.objects.filter(pk__in=entry_ids)
        .select_related("account", "to_account", "category", "property")
        .order_by("date", "id")
    )


def token(entries: list[Entry]) -> str:
    """Otisk označených pohybů včetně času poslední změny."""
    raw = ";".join(
        f"{e.pk}:{e.updated_at.isoformat()}" for e in sorted(entries, key=lambda e: e.pk)
    )
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class LeaseImpact:
    lease: Lease
    kind: str  # PaymentKind
    count: int
    amount_cents: int

    @property
    def label(self) -> str:
        return PaymentKind(self.kind).label

    @property
    def raises_balance(self) -> bool:
        """Smazaná platba zvýší dluh (saldo); vrácený přeplatek ho naopak sníží."""
        return self.kind == PaymentKind.PAYMENT


@dataclass
class Impacts:
    leases: list[LeaseImpact] = field(default_factory=list)
    reopened_dues: list[PayableDue] = field(default_factory=list)
    partly_paid_dues: list[PayableDue] = field(default_factory=list)
    repairs: list[Repair] = field(default_factory=list)
    inspections: list[Inspection] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(
            self.leases
            or self.reopened_dues
            or self.partly_paid_dues
            or self.repairs
            or self.inspections
        )


@dataclass
class DeleteSummary:
    entries: list[Entry]
    sums: dict[str, int]  # druh pohybu → součet
    impacts: Impacts
    token: str

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def sums_labeled(self) -> list[tuple[str, int]]:
        return [(EntryKind(kind).label, amount) for kind, amount in self.sums.items()]


def impacts_of(entries: list[Entry]) -> Impacts:
    ids = {e.pk for e in entries}
    impacts = Impacts()
    grouped: dict[tuple[int, str], list[RentPayment]] = defaultdict(list)
    payments = RentPayment.objects.filter(entry_id__in=ids).select_related("lease__property")
    leases: dict[int, Lease] = {}
    for payment in payments:
        grouped[(payment.lease_id, payment.kind)].append(payment)
        leases[payment.lease_id] = payment.lease
    for (lease_id, kind), items in sorted(grouped.items()):
        amount = sum(p.amount_cents for p in items)
        impacts.leases.append(LeaseImpact(leases[lease_id], kind, len(items), amount))
    dues = PayableDue.objects.filter(entries__in=ids).distinct().select_related("payable")
    for due in dues:
        remaining = due.entries.exclude(pk__in=ids).exists()
        (impacts.partly_paid_dues if remaining else impacts.reopened_dues).append(due)
    impacts.repairs = list(Repair.objects.filter(entry_id__in=ids).select_related("property"))
    impacts.inspections = list(
        Inspection.objects.filter(entry_id__in=ids).select_related("plan__property", "plan__type")
    )
    return impacts


def delete_summary(entry_ids: list[int]) -> DeleteSummary:
    if not entry_ids:
        raise ValidationError("Označ aspoň jeden pohyb.")
    if len(set(entry_ids)) > MAX_ENTRIES:
        raise ValidationError(f"Najednou jde smazat nejvýš {MAX_ENTRIES} pohybů.")
    entries = list(selected(entry_ids))
    if not entries:
        raise ValidationError("Označené pohyby už neexistují.")
    sums: dict[str, int] = {}
    for entry in entries:
        sums[entry.kind] = sums.get(entry.kind, 0) + entry.amount_cents
    order = list(EntryKind.values)
    sums = dict(sorted(sums.items(), key=lambda i: order.index(i[0])))
    return DeleteSummary(entries, sums, impacts_of(entries), token(entries))


@transaction.atomic
def delete_entries(entry_ids: list[int], confirmed_token: str) -> DeleteSummary:
    """Smaže označené pohyby, jen když se od potvrzení nezměnily (vše, nebo nic)."""
    entries = list(Entry.objects.select_for_update().filter(pk__in=entry_ids))
    if len(entries) != len(set(entry_ids)) or token(entries) != confirmed_token:
        raise ValidationError(
            "Některý z označených pohybů se mezitím změnil nebo zmizel – zkontroluj souhrn znovu."
        )
    summary = delete_summary(entry_ids)
    Entry.objects.filter(pk__in=[e.pk for e in entries]).delete()
    return summary
