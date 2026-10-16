"""Smlouvy a dodatky (P05)."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.core.formatting import format_czk
from apps.money.models import Account
from apps.rentals.models import Lease, LeaseAmendment, LeaseStatus, Property, Tenant
from apps.rentals.services.leases import (
    current_lease,
    end_lease,
    lease_end,
    save_amendment,
    save_lease,
    terms_at,
    terms_history,
)


def test_terms_follow_amendments(lease: Lease) -> None:
    assert terms_at(lease, date(2026, 6, 30)).total_cents == 1_800_000
    july = terms_at(lease, date(2026, 7, 1))
    assert (july.rent_cents, july.services_cents) == (1_600_000, 300_000)
    assert [p.start for p in terms_history(lease)] == [date(2026, 1, 1), date(2026, 7, 1)]
    LeaseAmendment.objects.create(
        lease=lease, effective_date=date(2026, 9, 1), end_date=date(2027, 12, 31)
    )
    assert lease_end(lease) == date(2027, 12, 31)
    assert terms_at(lease, date(2026, 8, 1)).end_date is None


def test_no_overlapping_leases(lease: Lease, tenant: Tenant) -> None:
    other = Lease(property=lease.property, start_date=date(2025, 1, 1), rent_cents=100)
    other.end_date = date(2026, 1, 1)
    with pytest.raises(ValidationError):
        save_lease(other, tenant, [])
    # Návrh se nepočítá, předchozí smlouva končící den před začátkem nevadí.
    draft = Lease(
        property=lease.property, start_date=date(2026, 3, 1), rent_cents=1, status=LeaseStatus.DRAFT
    )
    save_lease(draft, tenant, [])
    earlier = Lease(
        property=lease.property,
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        rent_cents=1,
        status=LeaseStatus.ENDED,
        terminated_on=date(2025, 12, 31),
    )
    save_lease(earlier, tenant, [])


def test_amendment_cannot_extend_into_next_lease(lease: Lease, tenant: Tenant) -> None:
    end_lease(lease, date(2026, 12, 31), "výpověď")
    following = Lease(property=lease.property, start_date=date(2027, 1, 1), rent_cents=1)
    save_lease(following, tenant, [])
    with pytest.raises(ValidationError):
        save_amendment(LeaseAmendment(lease=following, effective_date=date(2026, 12, 1)))


def test_end_lease(lease: Lease) -> None:
    with pytest.raises(ValidationError):
        end_lease(lease, date(2025, 12, 1), "")
    ended = end_lease(lease, date(2026, 9, 30), " dohoda ")
    assert ended.status == LeaseStatus.ENDED and ended.termination_reason == "dohoda"
    assert lease_end(ended) == date(2026, 9, 30)


def test_current_lease(lease: Lease) -> None:
    prop = Property.objects.prefetch_related("leases").get(pk=lease.property_id)
    assert current_lease(prop, date(2026, 10, 16)) == lease
    assert current_lease(prop, date(2025, 10, 16)) == lease  # nejbližší budoucí


def test_pages(auth_client: Client, lease: Lease) -> None:
    html = auth_client.get("/").content.decode()
    assert "Byt Laštůvkova" in html and "Jan Nájemník" in html
    html = auth_client.get(f"/properties/{lease.property_id}").content.decode()
    assert "777 123 456" in html and "Aktuální smlouva" in html
    html = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert format_czk(1_600_000) in html and "Historie podmínek" in html
    html = auth_client.get("/tenants").content.decode()
    assert "jan@example.cz" in html


@pytest.mark.parametrize(
    "url", ["/tenants", "/tenants/new", "/leases/new?property=1", "/properties/1"]
)
def test_pages_require_login(client: Client, db: None, url: str) -> None:
    assert client.get(url)["Location"].startswith("/login/")


def test_lease_pages_require_login(client: Client, lease: Lease) -> None:
    for url in (f"/leases/{lease.pk}", f"/leases/{lease.pk}/edit"):
        assert client.get(url)["Location"].startswith("/login/")
    response = client.post(f"/leases/{lease.pk}/payment", {"amount": "1"})
    assert response["Location"].startswith("/login/")


def test_create_property_tenant_lease(auth_client: Client, rental_account: Account) -> None:
    response = auth_client.post(
        "/properties/new",
        {"name": "Byt B", "layout": "1+kk", "account_id": str(rental_account.pk), "active": "on"},
    )
    prop = Property.objects.get(name="Byt B")
    assert response["Location"] == f"/properties/{prop.pk}"
    auth_client.post("/tenants/new", {"name": "Eva Nová", "active": "on"})
    eva = Tenant.objects.get(name="Eva Nová")
    page = auth_client.get(f"/leases/new?property={prop.pk}").content.decode()
    assert f'<option value="{rental_account.pk}" selected>' in page  # účet z bytu
    form = {
        "start_date": "2026-02-01",
        "rent_cents": "12 500",
        "services_cents": "2 000,50",
        "due_day": "10",
        "status": "ACTIVE",
        "account": str(rental_account.pk),
        "main_tenant": str(eva.pk),
    }
    response = auth_client.post(f"/leases/new?property={prop.pk}", form)
    lease = Lease.objects.get(property=prop)
    assert response["Location"] == f"/leases/{lease.pk}"
    assert (lease.rent_cents, lease.services_cents, lease.deposit_cents) == (1_250_000, 200_050, 0)
    assert list(lease.tenants.all()) == [eva]
    auth_client.post(
        f"/leases/{lease.pk}/amendments/new",
        {"effective_date": "2027-02-01", "rent_cents": "13 000"},
    )
    assert lease.amendments.get().rent_cents == 1_300_000
    auth_client.post(
        f"/leases/{lease.pk}/end",
        {"terminated_on": "2027-06-30", "reason": "odchod", "confirm": "on"},
    )
    lease.refresh_from_db()
    assert lease.status == LeaseStatus.ENDED


def test_lease_form_errors(auth_client: Client, lease: Lease, tenant: Tenant) -> None:
    form = {
        "start_date": "2026-03-01",
        "end_date": "2026-02-01",
        "rent_cents": "abc",
        "due_day": "40",
        "status": "ACTIVE",
        "main_tenant": str(tenant.pk),
    }
    text = auth_client.post(f"/leases/new?property={lease.property_id}", form).content.decode()
    assert "Zadej částku ve tvaru 1 234,50." in text
    assert "Konec nájmu nemůže být před jeho začátkem." in text
    assert "Zadej den 1–31." in text
    overlap = {**form, "end_date": "", "rent_cents": "1", "due_day": "5"}
    response = auth_client.post(f"/leases/new?property={lease.property_id}", overlap)
    assert "jinou smlouvu" in response.content.decode()
    assert Lease.objects.count() == 1


def test_only_draft_can_be_deleted(auth_client: Client, lease: Lease, tenant: Tenant) -> None:
    auth_client.post(f"/leases/{lease.pk}/delete")
    assert Lease.objects.filter(pk=lease.pk).exists()
    draft = save_lease(
        Lease(
            property=lease.property,
            start_date=date(2030, 1, 1),
            rent_cents=1,
            status=LeaseStatus.DRAFT,
        ),
        tenant,
        [],
    )
    response = auth_client.post(f"/leases/{draft.pk}/delete")
    assert response["Location"] == f"/properties/{lease.property_id}"
    assert not Lease.objects.filter(pk=draft.pk).exists()
