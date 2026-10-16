from datetime import date

import pytest

from apps.money.models import Account, AccountKind
from apps.rentals.models import Lease, LeaseAmendment, LeaseTenant, Property, Tenant, TenantRole


@pytest.fixture
def rental_account(db: None) -> Account:
    return Account.objects.create(name="Fio pronájmy", kind=AccountKind.BANK)


@pytest.fixture
def flat(rental_account: Account) -> Property:
    return Property.objects.create(name="Byt Laštůvkova", layout="2+1", account=rental_account)


@pytest.fixture
def tenant(db: None) -> Tenant:
    return Tenant.objects.create(name="Jan Nájemník", phone="777 123 456", email="jan@example.cz")


@pytest.fixture
def lease(flat: Property, tenant: Tenant, rental_account: Account) -> Lease:
    """Akceptační smlouva etapy 2: od 1. 1. 2026, 15 000 + 3 000 Kč, splatnost 5. dne,
    dodatek od 1. 7. 2026 s nájmem 16 000 Kč."""
    lease = Lease.objects.create(
        property=flat,
        number="1/2026",
        start_date=date(2026, 1, 1),
        rent_cents=1_500_000,
        services_cents=300_000,
        due_day=5,
        deposit_cents=3_600_000,
        account=rental_account,
    )
    LeaseTenant.objects.create(lease=lease, tenant=tenant, role=TenantRole.MAIN)
    LeaseAmendment.objects.create(
        lease=lease, number="1", effective_date=date(2026, 7, 1), rent_cents=1_600_000
    )
    return lease
