"""Databázové kontroly smluv, předpisů a plateb."""

from datetime import date

import pytest
from django.db import IntegrityError, transaction

from apps.money.models import Account, Entry, EntryKind
from apps.rentals.models import ChargeKind, Lease, PaymentKind, Property, RentCharge, RentPayment


def fails(create: object) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        create()  # type: ignore[operator]


def test_lease_checks(lease: Lease) -> None:
    flat = lease.property
    fails(lambda: Lease.objects.create(property=flat, start_date=date(2026, 1, 1), rent_cents=-1))
    fails(
        lambda: Lease.objects.create(
            property=flat, start_date=date(2026, 1, 1), end_date=date(2025, 12, 31), rent_cents=1
        )
    )
    fails(
        lambda: Lease.objects.create(
            property=flat, start_date=date(2026, 1, 1), rent_cents=1, due_day=0
        )
    )


def test_monthly_charge_unique(lease: Lease) -> None:
    month = date(2026, 1, 1)
    RentCharge.objects.create(
        lease=lease, kind=ChargeKind.RENT, period=month, due_date=month, amount_cents=1
    )
    fails(
        lambda: RentCharge.objects.create(
            lease=lease, kind=ChargeKind.RENT, period=month, due_date=month, amount_cents=1
        )
    )
    fails(
        lambda: RentCharge.objects.create(
            lease=lease, kind=ChargeKind.SERVICES, due_date=month, amount_cents=1
        )
    )
    # Jednorázové předpisy (vyúčtování, přeplatek) se mohou opakovat a být záporné.
    for _ in range(2):
        RentCharge.objects.create(
            lease=lease, kind=ChargeKind.SETTLEMENT, due_date=month, amount_cents=-500
        )


def test_payment_needs_entry_except_offset(lease: Lease, rental_account: Account) -> None:
    fails(lambda: RentPayment.objects.create(lease=lease, kind=PaymentKind.PAYMENT, amount_cents=1))
    fails(
        lambda: RentPayment.objects.create(
            lease=lease, kind=PaymentKind.DEPOSIT_OFFSET, amount_cents=1
        )
    )
    offset = RentPayment.objects.create(
        lease=lease, kind=PaymentKind.DEPOSIT_OFFSET, amount_cents=1, date=date(2026, 2, 1)
    )
    assert offset.paid_on == date(2026, 2, 1)
    entry = Entry.objects.create(
        date=date(2026, 1, 5), kind=EntryKind.DEPOSIT, amount_cents=100, account=rental_account
    )
    paid = RentPayment.objects.create(
        lease=lease, kind=PaymentKind.PAYMENT, amount_cents=100, entry=entry
    )
    assert paid.paid_on == date(2026, 1, 5)
    entry.delete()  # smazání pohybu vazbu odstraní
    assert not RentPayment.objects.filter(pk=paid.pk).exists()


def test_property_with_lease_is_protected(lease: Lease) -> None:
    fails(lambda: Property.objects.filter(pk=lease.property_id).delete())
