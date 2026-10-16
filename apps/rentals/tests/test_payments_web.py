"""Platby a předpisy na stránkách (P06, P07)."""

from datetime import date

from django.test import Client

from apps.core.formatting import format_czk
from apps.money.models import Account, Category, CategoryCode, Entry, EntryKind
from apps.rentals.models import ChargeKind, Lease, LeaseStatus, PaymentKind, RentCharge
from apps.rentals.services.charges import ensure_charges, lease_balance
from apps.rentals.services.payments import record_payment


def test_lease_page_shows_balance(auth_client: Client, lease: Lease) -> None:
    html = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert "Saldo (dluh)" in html and "Předpisy" in html and "Zapsat přijatou platbu" in html
    overview = auth_client.get("/").content.decode()
    assert "Po splatnosti celkem" in overview and "po splatnosti" in overview


def test_overview_without_debt(auth_client: Client, db: None) -> None:
    assert "Nikdo nedluží" in auth_client.get("/").content.decode()


def test_record_payment_via_web(auth_client: Client, lease: Lease, rental_account: Account) -> None:
    response = auth_client.post(
        f"/leases/{lease.pk}/payment",
        {
            "day": "2026-01-05",
            "amount": "18 000",
            "deposit_amount": "36 000",
            "account": str(rental_account.pk),
            "note": "",
        },
    )
    assert response["Location"] == f"/leases/{lease.pk}"
    kinds = sorted(p.kind for p in lease.payments.all())
    assert kinds == [PaymentKind.DEPOSIT, PaymentKind.PAYMENT, PaymentKind.PAYMENT]
    assert Entry.objects.filter(property=lease.property).count() == 3
    response = auth_client.post(
        f"/leases/{lease.pk}/payment",
        {"day": "2026-01-05", "amount": "", "account": str(rental_account.pk)},
    )
    assert "Zadej částku." in response.content.decode()


def test_export_has_no_tenant_contacts(
    auth_client: Client, lease: Lease, rental_account: Account
) -> None:
    day = date(2026, 1, 5)
    record_payment(lease, day=day, amount=1_800_000, account_id=rental_account.pk, today=day)
    content = auth_client.get("/entries/export.csv").content.decode("utf-8-sig")
    assert "Jan Nájemník" in content
    assert "777 123 456" not in content and "jan@example.cz" not in content


def test_manual_charge_and_restore(auth_client: Client, lease: Lease) -> None:
    auth_client.post(
        f"/leases/{lease.pk}/charges/new",
        {"kind": "SETTLEMENT", "due_date": "2026-05-31", "amount_cents": "-1 200", "note": "2025"},
    )
    settlement = lease.charges.get(kind=ChargeKind.SETTLEMENT)
    assert settlement.amount_cents == -120_000 and settlement.manual
    ensure_charges(lease, date(2026, 10, 16))
    march = lease.charges.get(kind=ChargeKind.RENT, period=date(2026, 3, 1))
    auth_client.post(
        f"/leases/{lease.pk}/charges/{march.pk}/edit",
        {"due_date": "2026-03-05", "amount_cents": "10 000", "note": "sleva"},
    )
    march.refresh_from_db()
    assert march.amount_cents == 1_000_000 and march.manual and march.kind == ChargeKind.RENT
    auth_client.post(f"/leases/{lease.pk}/charges/{march.pk}/delete")
    auth_client.get(f"/leases/{lease.pk}")  # doplní automatický předpis
    assert (
        lease.charges.get(kind=ChargeKind.RENT, period=date(2026, 3, 1)).amount_cents == 1_500_000
    )


def test_end_requires_confirmation(auth_client: Client, lease: Lease) -> None:
    form = {"terminated_on": "2026-03-31", "reason": "dohoda"}
    response = auth_client.post(f"/leases/{lease.pk}/end", form)
    assert "ukončení potvrď" in response.content.decode()
    lease.refresh_from_db()
    assert lease.status == LeaseStatus.ACTIVE
    auth_client.post(f"/leases/{lease.pk}/end", {**form, "confirm": "on"})
    lease.refresh_from_db()
    assert lease.status == LeaseStatus.ENDED


def test_link_and_unlink(auth_client: Client, lease: Lease, rental_account: Account) -> None:
    entry = Entry.objects.create(
        date=date(2026, 2, 3),
        kind=EntryKind.INCOME,
        amount_cents=1_800_000,
        category=Category.objects.get(code=CategoryCode.RENT),
        account=rental_account,
        property=lease.property,
    )
    html = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert "Přiřadit existující příjem (1)" in html
    auth_client.post(f"/leases/{lease.pk}/link", {"entry": str(entry.pk), "kind": "PAYMENT"})
    payment = lease.payments.get()
    assert payment.entry == entry
    auth_client.post(f"/leases/{lease.pk}/payments/{payment.pk}/unlink")
    assert not lease.payments.exists() and Entry.objects.filter(pk=entry.pk).exists()


def test_deposit_return_page(auth_client: Client, lease: Lease, rental_account: Account) -> None:
    day = date(2026, 1, 2)
    record_payment(
        lease, day=day, amount=0, deposit_amount=3_600_000, account_id=rental_account.pk, today=day
    )
    html = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert "Vrátit jistotu" in html and format_czk(3_600_000) in html
    response = auth_client.post(
        f"/leases/{lease.pk}/payout/DEPOSIT_RETURN",
        {"day": "2026-10-16", "amount": "40 000", "account": str(rental_account.pk)},
    )
    assert "nejvýš drženou jistotu" in response.content.decode()
    auth_client.post(
        f"/leases/{lease.pk}/payout/DEPOSIT_RETURN",
        {"day": "2026-10-16", "amount": "36 000", "account": str(rental_account.pk)},
    )
    assert lease_balance(lease, date(2026, 10, 16)).deposit.held == 0
    assert auth_client.post(f"/leases/{lease.pk}/payout/NIC").status_code == 404
    assert RentCharge.objects.filter(lease=lease, kind=ChargeKind.DEPOSIT).exists()


def test_property_card(auth_client: Client, lease: Lease, rental_account: Account) -> None:
    day = date(2026, 1, 5)
    record_payment(lease, day=day, amount=1_800_000, account_id=rental_account.pk, today=day)
    html = auth_client.get(f"/properties/{lease.property_id}").content.decode()
    assert "Pohyby bytu" in html and "Nájemné" in html and "po splatnosti" in html
