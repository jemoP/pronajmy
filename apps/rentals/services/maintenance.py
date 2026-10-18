"""Komunikace (P08), opravy (P09) a pravidelné revize (P10).

Náklady oprav a revizí jsou běžné pohyby (náklad s účelem podle kódu a bytem);
oprava i revize na pohyb jen odkazují.
"""

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.db.models import Prefetch, QuerySet

from apps.core.dates import add_months
from apps.money.models import CategoryCode, Entry, EntryKind
from apps.money.services.entries import EntryInput, create_entry
from apps.rentals.models import (
    OPEN_REPAIR,
    Communication,
    Inspection,
    InspectionPlan,
    PaidBy,
    Property,
    Repair,
    RepairStatus,
    with_attachment_count,
)
from apps.rentals.services.payments import category_id


def expense(
    prop: Property, *, day: date, amount: int, account_id: int, code: CategoryCode, note: str
) -> Entry:
    return create_entry(
        EntryInput(
            date=day,
            kind=EntryKind.EXPENSE,
            amount_cents=amount,
            account_id=account_id,
            category_id=category_id(code),
            property_id=prop.pk,
            note=note,
        )
    )


def with_contractor(label: str, contractor: str) -> str:
    return f"{label} ({contractor})" if contractor else label


# --- Opravy ------------------------------------------------------------------


@transaction.atomic
def save_repair(repair: Repair, *, account_id: int | None, today: date) -> Repair:
    """Uloží opravu; s účtem a náklady (platí pronajímatel) zapíše náklad, pokud ještě není."""
    if repair.status == RepairStatus.DONE and repair.done_date is None:
        repair.done_date = today
    repair.save()
    if (
        account_id is not None
        and repair.cost_cents
        and repair.paid_by == PaidBy.OWNER
        and repair.entry_id is None
    ):
        repair.entry = expense(
            repair.property,
            day=repair.done_date or today,
            amount=repair.cost_cents,
            account_id=account_id,
            code=CategoryCode.REPAIRS,
            note=with_contractor(f"Oprava – {repair.title}", repair.contractor),
        )
        repair.save(update_fields=["entry"])
    return repair


def open_repairs(prop: Property | None = None) -> QuerySet[Repair]:
    qs = with_attachment_count(Repair.objects.filter(status__in=OPEN_REPAIR)).select_related(
        "property"
    )
    if prop is not None:
        qs = qs.filter(property=prop)
    return qs.order_by("reported_date", "id")


# --- Revize ------------------------------------------------------------------


def interval(plan: InspectionPlan) -> int:
    return plan.interval_months or plan.type.interval_months


@dataclass(frozen=True)
class PlanState:
    plan: InspectionPlan
    last: Inspection | None
    due: date | None
    days_left: int | None

    @property
    def overdue(self) -> bool:
        return self.days_left is not None and self.days_left < 0

    @property
    def soon(self) -> bool:
        """Termín v okně upozornění druhu revize (výchozí 30 dní)."""
        return self.days_left is not None and 0 <= self.days_left <= self.plan.type.remind_days


def plan_state(plan: InspectionPlan, today: date) -> PlanState:
    inspections = sorted(plan.inspections.all(), key=lambda i: (i.done_date, i.id))
    last = inspections[-1] if inspections else None
    due = last.next_due_date if last else plan.first_due_date
    return PlanState(plan, last, due, (due - today).days if due else None)


def plan_states(today: date, prop: Property | None = None) -> list[PlanState]:
    """Aktivní plány seřazené podle příštího termínu (bez termínu na konci)."""
    qs = InspectionPlan.objects.filter(active=True).select_related("type", "property")
    if prop is not None:
        qs = qs.filter(property=prop)
    inspections = Prefetch("inspections", queryset=with_attachment_count(Inspection.objects.all()))
    states = [plan_state(p, today) for p in qs.prefetch_related(inspections)]
    return sorted(states, key=lambda s: (s.due is None, s.due or date.max, s.plan.pk))


def _auto_due(inspection: Inspection) -> bool:
    """Má se příští termín dopočítat? Prázdný vždy; po změně data provedení jen tehdy,
    když zůstal automaticky dopočtený z původního data (ruční termín se nemění)."""
    if inspection.next_due_date is None:
        return True
    if inspection.pk is None:
        return False
    original = Inspection.objects.filter(pk=inspection.pk).first()
    if original is None or original.done_date == inspection.done_date:
        return False
    previous_auto = add_months(original.done_date, interval(inspection.plan))
    return inspection.next_due_date == original.next_due_date == previous_auto


@transaction.atomic
def save_inspection(inspection: Inspection, *, account_id: int | None) -> Inspection:
    """Uloží revizi; příští termín = provedení + interval (není-li zadaný ručně).
    S účtem a náklady zapíše náklad Revize, pokud ještě není."""
    plan = inspection.plan
    if _auto_due(inspection):
        inspection.next_due_date = add_months(inspection.done_date, interval(plan))
    inspection.save()
    if account_id is not None and inspection.cost_cents and inspection.entry_id is None:
        inspection.entry = expense(
            plan.property,
            day=inspection.done_date,
            amount=inspection.cost_cents,
            account_id=account_id,
            code=CategoryCode.INSPECTION,
            note=with_contractor(f"Revize – {plan}", inspection.contractor),
        )
        inspection.save(update_fields=["entry"])
    return inspection


# --- Komunikace --------------------------------------------------------------


def open_follow_ups(prop: Property | None = None) -> QuerySet[Communication]:
    """Komunikace s termínem vyřízení, která ještě není vyřízená."""
    qs = with_attachment_count(
        Communication.objects.filter(follow_up_date__isnull=False, follow_up_done=False)
    ).select_related("property", "tenant", "lease__property")
    if prop is not None:
        qs = qs.filter(property=prop)
    return qs.order_by("follow_up_date", "id")
