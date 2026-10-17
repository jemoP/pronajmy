"""Smlouvy a dodatky (P05): podmínky k datu, historie, překrývání smluv."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch

from apps.rentals.models import (
    Lease,
    LeaseAmendment,
    LeaseStatus,
    LeaseTenant,
    Property,
    Tenant,
    TenantRole,
)


@dataclass(frozen=True)
class Terms:
    rent_cents: int
    services_cents: int
    end_date: date | None

    @property
    def total_cents(self) -> int:
        return self.rent_cents + self.services_cents


@dataclass(frozen=True)
class TermsPeriod:
    start: date
    terms: Terms
    amendment: LeaseAmendment | None  # None = výchozí podmínky smlouvy


def _amendments(lease: Lease) -> list[LeaseAmendment]:
    return sorted(lease.amendments.all(), key=lambda a: (a.effective_date, a.id))


def terms_at(lease: Lease, day: date) -> Terms:
    """Podmínky platné v daný den: smlouva + dodatky účinné nejpozději ten den."""
    rent, services, end = lease.rent_cents, lease.services_cents, lease.end_date
    for amendment in _amendments(lease):
        if amendment.effective_date > day:
            break
        if amendment.rent_cents is not None:
            rent = amendment.rent_cents
        if amendment.services_cents is not None:
            services = amendment.services_cents
        if amendment.end_date is not None:
            end = amendment.end_date
    return Terms(rent, services, end)


def terms_history(lease: Lease) -> list[TermsPeriod]:
    periods = [TermsPeriod(lease.start_date, terms_at(lease, lease.start_date), None)]
    for amendment in _amendments(lease):
        periods.append(
            TermsPeriod(
                amendment.effective_date, terms_at(lease, amendment.effective_date), amendment
            )
        )
    return periods


def lease_end(lease: Lease) -> date | None:
    """Skutečný konec nájmu: ukončení, jinak sjednaný konec (i z dodatku); None = neurčitá."""
    if lease.terminated_on:
        return lease.terminated_on
    return terms_at(lease, date.max).end_date


def leases_with_details() -> Any:
    """Prefetch smluv bytu s dodatky a nájemníky (pro karty a přehled)."""
    return Prefetch(
        "leases",
        queryset=Lease.objects.prefetch_related("amendments", "lease_tenants__tenant").order_by(
            "-start_date"
        ),
    )


def current_lease(prop: Property, today: date) -> Lease | None:
    """Platná smlouva bytu dnes, jinak nejbližší budoucí platná."""
    leases = [lease for lease in prop.leases.all() if lease.status == LeaseStatus.ACTIVE]
    running = [lease for lease in leases if lease.start_date <= today]
    if running:
        return max(running, key=lambda lease: lease.start_date)
    upcoming = sorted(leases, key=lambda lease: lease.start_date)
    return upcoming[0] if upcoming else None


def tenant_names(lease: Lease) -> str:
    rows = sorted(lease.lease_tenants.all(), key=lambda lt: (lt.role != TenantRole.MAIN, lt.id))
    return ", ".join(lt.tenant.name for lt in rows)


def check_overlap(lease: Lease) -> None:
    """Na jeden byt nejvýš jedna smlouva v daném dni (návrhy se nepočítají)."""
    if lease.status == LeaseStatus.DRAFT:
        return
    end = lease_end(lease) or date.max
    others = (
        Lease.objects.filter(property_id=lease.property_id)
        .exclude(status=LeaseStatus.DRAFT)
        .exclude(pk=lease.pk)
        .prefetch_related("amendments")
    )
    for other in others:
        other_end = lease_end(other) or date.max
        if lease.start_date <= other_end and other.start_date <= end:
            raise ValidationError({"start_date": f"Byt má v tomto období jinou smlouvu ({other})."})


def check_status(lease: Lease) -> None:
    errors: dict[str, str] = {}
    if lease.status == LeaseStatus.ENDED and lease.terminated_on is None:
        errors["terminated_on"] = "Ukončená smlouva musí mít datum ukončení."
    if lease.terminated_on and lease.terminated_on < lease.start_date:
        errors["terminated_on"] = "Smlouva nemůže skončit před začátkem nájmu."
    if lease.charges_from and lease.charges_from < lease.start_date:
        errors["charges_from"] = "Saldo jde sledovat nejdřív od začátku nájmu."
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def save_lease(lease: Lease, main_tenant: Tenant, co_tenants: list[Tenant]) -> Lease:
    """Uloží smlouvu (už naplněnou z formuláře) a její nájemníky."""
    check_status(lease)
    lease.save()
    check_overlap(lease)
    lease.lease_tenants.all().delete()
    LeaseTenant.objects.create(lease=lease, tenant=main_tenant, role=TenantRole.MAIN)
    for tenant in co_tenants:
        if tenant.pk != main_tenant.pk:
            LeaseTenant.objects.create(lease=lease, tenant=tenant, role=TenantRole.CO_TENANT)
    return lease


@transaction.atomic
def save_amendment(amendment: LeaseAmendment) -> LeaseAmendment:
    lease = amendment.lease
    if amendment.effective_date < lease.start_date:
        raise ValidationError({"effective_date": "Dodatek nemůže platit před začátkem nájmu."})
    if amendment.end_date and amendment.end_date < lease.start_date:
        raise ValidationError({"end_date": "Nájem nemůže skončit před svým začátkem."})
    amendment.save()
    check_overlap(lease)
    return amendment


@transaction.atomic
def end_lease(lease: Lease, terminated_on: date, reason: str) -> Lease:
    lease.status = LeaseStatus.ENDED
    lease.terminated_on = terminated_on
    lease.termination_reason = reason.strip()
    check_status(lease)
    lease.save()
    return lease
