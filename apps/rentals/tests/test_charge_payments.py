"""Platba z předpisu jednotlivě i dávkově (ZM-005)."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.money.models import Account, CategoryCode, Entry
from apps.rentals.models import ChargeKind, Lease, PaymentKind, RentCharge, RentPayment
from apps.rentals.services.charges import ensure_charges, lease_balance
from apps.rentals.services.leases import end_lease
from apps.rentals.services.payments import pay_charges, record_payment

TODAY = date(2026, 10, 16)


def charge(lease: Lease, kind: ChargeKind, month: int) -> RentCharge:
    ensure_charges(lease, TODAY)
    return lease.charges.get(kind=kind, period=date(2026, month, 1))


def state(lease: Lease, item: RentCharge) -> tuple[int, int]:
    """(nezaplaceno, počet plateb s vazbou) daného předpisu."""
    balance = lease_balance(lease, TODAY)
    found = next(s for s in [*balance.charges, *balance.deposit_charges] if s.charge == item)
    return found.open_cents, len(found.paid_by)


def pay(lease: Lease, account: Account, *items: RentCharge, day: date | None = None) -> list[Entry]:
    return pay_charges(lease, [i.pk for i in items], day=day, account_id=account.pk, today=TODAY)


def test_single_charge_becomes_payment(lease: Lease, rental_account: Account) -> None:
    september = charge(lease, ChargeKind.RENT, 9)
    (entry,) = pay(lease, rental_account, september)
    assert (entry.date, entry.amount_cents, entry.property_id) == (
        date(2026, 9, 5),  # podle splatnosti
        1_600_000,
        lease.property_id,
    )
    assert entry.category is not None and entry.category.code == CategoryCode.RENT
    assert "Nájem 9/2026" in entry.note and "Jan Nájemník" in entry.note
    payment = RentPayment.objects.get(entry=entry)
    assert (payment.charge, payment.kind) == (september, PaymentKind.PAYMENT)
    assert state(lease, september) == (0, 1)


def test_paying_out_of_order_marks_the_right_charge(lease: Lease, rental_account: Account) -> None:
    """Platba říjnového nájmu kryje říjen, ne nejstarší dluh; saldo je stejné jako u FIFO."""
    ensure_charges(lease, TODAY)
    before = lease_balance(lease, TODAY)
    october = charge(lease, ChargeKind.RENT, 10)
    pay(lease, rental_account, october)
    after = lease_balance(lease, TODAY)
    assert after.balance == before.balance - 1_600_000
    assert state(lease, october) == (0, 1)
    assert state(lease, charge(lease, ChargeKind.RENT, 1))[0] == 1_500_000  # leden dál dluží


def test_partly_paid_charge_pays_only_the_rest(lease: Lease, rental_account: Account) -> None:
    day = date(2026, 1, 5)
    record_payment(lease, day=day, amount=1_000_000, account_id=rental_account.pk, today=day)
    january = charge(lease, ChargeKind.RENT, 1)
    assert state(lease, january) == (500_000, 0)  # FIFO pokrylo část
    (entry,) = pay(lease, rental_account, january)
    assert entry.amount_cents == 500_000
    assert state(lease, january) == (0, 1)


def test_batch_one_payment_per_charge(lease: Lease, rental_account: Account) -> None:
    items = [
        charge(lease, kind, m) for m in (1, 2, 3) for kind in (ChargeKind.RENT, ChargeKind.SERVICES)
    ]
    before = lease_balance(lease, TODAY).overdue
    entries = pay(lease, rental_account, *items, day=date(2026, 10, 1))
    assert len(entries) == 6 and {e.date for e in entries} == {date(2026, 10, 1)}
    codes = sorted(str(e.category.code) for e in entries if e.category)
    assert codes == ["RENT"] * 3 + ["SERVICES"] * 3
    assert lease_balance(lease, TODAY).overdue == before - 3 * 1_800_000
    assert all(state(lease, i)[0] == 0 for i in items)


def test_deposit_charge(lease: Lease, rental_account: Account) -> None:
    ensure_charges(lease, TODAY)
    deposit = lease.charges.get(kind=ChargeKind.DEPOSIT)
    (entry,) = pay(lease, rental_account, deposit)
    assert entry.category is not None and entry.category.code == CategoryCode.DEPOSIT
    assert RentPayment.objects.get(entry=entry).kind == PaymentKind.DEPOSIT
    balance = lease_balance(lease, TODAY)
    assert balance.deposit.received == 3_600_000 and state(lease, deposit) == (0, 1)
    assert balance.paid == 0  # jistota mimo saldo


def test_future_due_date_uses_today(lease: Lease, rental_account: Account) -> None:
    lease.due_day = 31
    lease.save()
    (entry,) = pay(lease, rental_account, charge(lease, ChargeKind.RENT, 10))
    assert entry.date == TODAY  # splatnost 31. 10. je v budoucnosti


def test_errors_write_nothing(lease: Lease, rental_account: Account) -> None:
    january, february = charge(lease, ChargeKind.RENT, 1), charge(lease, ChargeKind.RENT, 2)
    pay(lease, rental_account, january)
    count = Entry.objects.count()
    with pytest.raises(ValidationError, match="nic k zaplacení"):
        pay(lease, rental_account, february, january)  # leden je už zaplacený
    with pytest.raises(ValidationError, match="v budoucnosti"):
        pay(lease, rental_account, february, day=date(2026, 10, 17))
    with pytest.raises(ValidationError, match="aspoň jeden"):
        pay(lease, rental_account)
    other = RentCharge.objects.create(
        lease=lease, kind=ChargeKind.OTHER, due_date=TODAY, amount_cents=-100, manual=True
    )
    with pytest.raises(ValidationError, match="nic k zaplacení"):
        pay(lease, rental_account, other)  # záporný předpis
    assert Entry.objects.count() == count


def test_not_before_tracking_start(lease: Lease, rental_account: Account) -> None:
    lease.charges_from = date(2026, 9, 1)
    lease.save()
    september = charge(lease, ChargeKind.RENT, 9)
    with pytest.raises(ValidationError, match="před začátkem sledování"):
        pay(lease, rental_account, september, day=date(2026, 8, 31))


def test_removed_charge_falls_back_to_fifo(lease: Lease, rental_account: Account) -> None:
    september = charge(lease, ChargeKind.RENT, 9)
    (entry,) = pay(lease, rental_account, september)
    end_lease(lease, date(2026, 8, 31), "dohoda")
    ensure_charges(lease, TODAY)  # zářijový předpis zmizí
    payment = RentPayment.objects.get(entry=entry)
    assert payment.charge is None
    balance = lease_balance(lease, TODAY)
    assert balance.paid == 1_600_000  # platba zůstala, kryje FIFO od ledna
    assert balance.charged == 6 * 1_800_000 + 2 * 1_900_000


def test_pay_charges_via_web(auth_client: Client, lease: Lease, rental_account: Account) -> None:
    september = charge(lease, ChargeKind.RENT, 9)
    october = charge(lease, ChargeKind.SERVICES, 10)
    html = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert "Platba z předpisů" in html and f'name="single" value="{september.pk}"' in html
    form = {"date_mode": "due", "account": str(rental_account.pk), "note": ""}
    response = auth_client.post(
        f"/leases/{lease.pk}/charges/pay", {**form, "single": str(september.pk)}
    )
    assert response["Location"] == f"/leases/{lease.pk}#predpisy"
    assert RentPayment.objects.get().charge == september
    html = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert "platba" in html and "5. 9. 2026" in html
    assert f'name="single" value="{september.pk}"' not in html  # zaplacený se nenabízí
    # Dávka s jedním datem; chybějící datum a prázdný výběr vrátí chybu.
    page = auth_client.post(
        f"/leases/{lease.pk}/charges/pay",
        {**form, "date_mode": "day", "charges": [str(october.pk)]},
    ).content.decode()
    assert "Zadej datum platby." in page
    page = auth_client.post(f"/leases/{lease.pk}/charges/pay", form).content.decode()
    assert "Označ aspoň jeden předpis." in page
    auth_client.post(
        f"/leases/{lease.pk}/charges/pay",
        {**form, "date_mode": "day", "day": "2026-10-10", "charges": [str(october.pk)]},
    )
    assert RentPayment.objects.get(charge=october).entry.date == date(2026, 10, 10)  # type: ignore[union-attr]
