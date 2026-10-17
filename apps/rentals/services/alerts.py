"""Upozornění (P11): nájem po splatnosti, konec smlouvy, revize, opravy, komunikace."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.urls import reverse

from apps.core.formatting import format_czk, format_date
from apps.rentals.models import Lease, LeaseStatus
from apps.rentals.services.charges import BALANCE_PREFETCH, ensure_all_charges, lease_balance
from apps.rentals.services.leases import lease_end, tenant_names
from apps.rentals.services.maintenance import open_follow_ups, open_repairs, plan_states

LEASE_END_DAYS = 60  # upozornit na konec smlouvy tolik dní předem
FOLLOW_UP_DAYS = 3  # komunikaci k vyřízení ukázat tolik dní předem

OVER = "over"
WARNING = "warning"


@dataclass(frozen=True)
class Alert:
    level: str  # OVER = po termínu, WARNING = blíží se
    text: str
    url: str
    day: date  # termín, podle kterého se řadí


def lease_alerts(today: date) -> list[Alert]:
    alerts: list[Alert] = []
    leases = (
        Lease.objects.exclude(status=LeaseStatus.DRAFT)
        .select_related("property")
        .prefetch_related(*BALANCE_PREFETCH, "lease_tenants__tenant")
    )
    for lease in leases:
        url = reverse("rentals:lease", args=[lease.pk])
        balance = lease_balance(lease, today)
        if balance.overdue and balance.oldest_overdue:
            who = tenant_names(lease) or lease.property.name
            text = (
                f"Nájem po splatnosti: {lease.property} – {who} dluží"
                f" {format_czk(balance.overdue)} (od {format_date(balance.oldest_overdue)})."
            )
            alerts.append(Alert(OVER, text, url, balance.oldest_overdue))
        end = lease_end(lease) if lease.status == LeaseStatus.ACTIVE else None
        if end and end < today:
            text = (
                f"Smlouva {lease.property} skončila {format_date(end)} – ukonči ji,"
                " nebo zapiš dodatek o prodloužení."
            )
            alerts.append(Alert(OVER, text, url, end))
        elif end and (days := (end - today).days) <= LEASE_END_DAYS:
            text = f"Smlouva {lease.property} končí {format_date(end)} (za {days} dní)."
            alerts.append(Alert(WARNING, text, url, end))
    return alerts


def maintenance_alerts(today: date) -> list[Alert]:
    alerts: list[Alert] = []
    for state in plan_states(today):
        if state.due is None:
            continue
        plan = state.plan
        url = f"{reverse('rentals:property', args=[plan.property_id])}#revize"
        if state.overdue:
            text = f"Revize {plan} ({plan.property}) je po termínu {format_date(state.due)}."
            alerts.append(Alert(OVER, text, url, state.due))
        elif state.soon:
            text = (
                f"Revize {plan} ({plan.property}) {format_date(state.due)}"
                f" – za {state.days_left} dní."
            )
            alerts.append(Alert(WARNING, text, url, state.due))
    repairs = list(open_repairs())
    if repairs:
        text = f"Otevřené opravy: {len(repairs)}."
        alerts.append(Alert(WARNING, text, reverse("rentals:repairs"), repairs[0].reported_date))
    for item in open_follow_ups():
        assert item.follow_up_date is not None
        if item.follow_up_date > today + timedelta(days=FOLLOW_UP_DAYS):
            continue
        where = f" ({item.property})" if item.property else ""
        level = OVER if item.follow_up_date < today else WARNING
        text = f"Vyřídit: {item.subject}{where} do {format_date(item.follow_up_date)}."
        url = reverse("rentals:communication_edit", args=[item.pk])
        alerts.append(Alert(level, text, url, item.follow_up_date))
    return alerts


def rental_alerts(today: date) -> list[Alert]:
    """Upozornění seřazená: nejdřív po termínu, uvnitř podle data (nejstarší nahoře)."""
    ensure_all_charges(today)
    alerts = lease_alerts(today) + maintenance_alerts(today)
    return sorted(alerts, key=lambda a: (a.level != OVER, a.day))
