"""První kroky na prázdném Přehledu (ZM-010)."""

from datetime import date

from django.test import Client

from apps.money.models import Account, AccountKind
from apps.rentals.models import Lease, LeaseStatus, LeaseTenant, Property, Tenant, TenantRole


def test_first_steps_on_clean_install(auth_client: Client) -> None:
    html = auth_client.get("/").content.decode()
    assert "První kroky" in html and "Založ účet" in html and "(hotovo)" not in html


def test_first_steps_mark_done_and_disappear(auth_client: Client) -> None:
    account = Account.objects.create(name="Účet", kind=AccountKind.BANK)
    prop = Property.objects.create(name="Byt", account=account)
    tenant = Tenant.objects.create(name="Nájemník")
    html = auth_client.get("/").content.decode()
    assert html.count("(hotovo)") == 3

    lease = Lease.objects.create(
        property=prop, start_date=date(2026, 1, 1), rent_cents=100_00, status=LeaseStatus.ACTIVE
    )
    LeaseTenant.objects.create(lease=lease, tenant=tenant, role=TenantRole.MAIN)
    assert "První kroky" not in auth_client.get("/").content.decode()
