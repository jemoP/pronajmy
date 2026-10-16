"""Předpisy, platby, saldo a jistota (P06, P07)."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.money.models import Account, Category, CategoryCode, Entry, EntryKind
from apps.money.services.entries import EntryInput, result_for, update_entry
from apps.rentals.models import (
    ChargeKind,
    Lease,
    LeaseAmendment,
    PaymentKind,
    Property,
    RentCharge,
)
from apps.rentals.services.charges import ensure_charges, lease_balance, prorate
from apps.rentals.services.leases import end_lease
from apps.rentals.services.payments import (
    link_entry,
    offset_deposit,
    pay_out,
    record_payment,
    suggestions,
)

TODAY = date(2026, 10, 16)


def pay_monthly(lease: Lease, account: Account, months: range, amount: int) -> None:
    for month in months:
        day = date(2026, month, 5)
        record_payment(lease, day=day, amount=amount, account_id=account.pk, today=day)


def by_category(lease: Lease) -> dict[str, int]:
    result: dict[str, int] = {}
    for p in lease.payments.select_related("entry__category"):
        assert p.entry is not None and p.entry.category is not None
        code = str(p.entry.category.code)
        result[code] = result.get(code, 0) + p.amount_cents
    return result


def test_acceptance_debt(lease: Lease, rental_account: Account) -> None:
    """Akceptace etapy 2: platby 18 000 Kč za leden–září → k 16. 10. 2026 dluh 22 000 Kč
    po splatnosti; platby rozdělené na nájemné 138 000 Kč a zálohy 24 000 Kč."""
    pay_monthly(lease, rental_account, range(1, 10), 1_800_000)
    ensure_charges(lease, TODAY)
    balance = lease_balance(lease, TODAY)
    assert balance.charged == 6 * 1_800_000 + 4 * 1_900_000
    assert balance.paid == 9 * 1_800_000
    assert balance.balance == 2_200_000
    assert balance.overdue == 2_200_000
    assert balance.oldest_overdue == date(2026, 9, 5)
    assert by_category(lease) == {"RENT": 13_800_000, "SERVICES": 2_400_000}
    entry = Entry.objects.filter(property=lease.property).first()
    assert entry is not None and entry.account == rental_account
    assert entry.kind == EntryKind.INCOME and "Jan Nájemník" in entry.note
    # Platby jsou příjmy bytu ve výsledku.
    year = result_for(date(2026, 1, 1), date(2026, 12, 31), TODAY, lease.property_id)
    assert year.income_cents == 9 * 1_800_000


def test_category_found_by_code_after_rename(lease: Lease, rental_account: Account) -> None:
    Category.objects.filter(code=CategoryCode.RENT).update(name="Nájem bytu")
    record_payment(
        lease,
        day=date(2026, 1, 5),
        amount=1_500_000,
        account_id=rental_account.pk,
        today=date(2026, 1, 5),
    )
    assert by_category(lease) == {"RENT": 1_500_000}


def test_charges_follow_terms_and_keep_manual(lease: Lease) -> None:
    ensure_charges(lease, TODAY)
    assert lease.charges.filter(kind=ChargeKind.RENT).count() == 10
    july = lease.charges.get(kind=ChargeKind.RENT, period=date(2026, 7, 1))
    assert july.amount_cents == 1_600_000 and july.due_date == date(2026, 7, 5)
    august = lease.charges.get(kind=ChargeKind.RENT, period=date(2026, 8, 1))
    august.amount_cents, august.manual = 1_000_000, True  # sleva za opravu
    august.save()
    LeaseAmendment.objects.create(
        lease=lease, effective_date=date(2026, 8, 1), rent_cents=1_700_000
    )
    ensure_charges(lease, TODAY)
    rent = lease.charges.filter(kind=ChargeKind.RENT)
    assert rent.get(period=date(2026, 8, 1)).amount_cents == 1_000_000
    assert rent.get(period=date(2026, 9, 1)).amount_cents == 1_700_000
    ensure_charges(lease, TODAY)  # idempotentní
    assert rent.count() == 10
    assert lease.charges.get(kind=ChargeKind.DEPOSIT).amount_cents == 3_600_000


def test_due_date_in_short_month(lease: Lease) -> None:
    lease.due_day = 31
    lease.save()
    ensure_charges(lease, TODAY)
    feb = lease.charges.get(kind=ChargeKind.RENT, period=date(2026, 2, 1))
    assert feb.due_date == date(2026, 2, 28)


def test_partial_months_and_end(lease: Lease) -> None:
    assert prorate(1_500_000, date(2026, 1, 1), date(2026, 1, 16), None) == 774_200
    end_lease(lease, date(2026, 8, 15), "výpověď")
    ensure_charges(lease, TODAY)
    rents = lease.charges.filter(kind=ChargeKind.RENT).order_by("period")
    assert [c.period for c in rents][-1] == date(2026, 8, 1)
    # Srpen do 15.: 16 000 × 15/31 = 7 741,94 → 7 742 Kč
    assert rents.last().amount_cents == 774_200  # type: ignore[union-attr]


def test_charges_from_skips_history(lease: Lease) -> None:
    lease.charges_from = date(2026, 9, 1)
    lease.save()
    ensure_charges(lease, TODAY)
    assert lease.charges.filter(kind=ChargeKind.RENT).count() == 2
    assert not lease.charges.filter(kind=ChargeKind.DEPOSIT).exists()


def test_deposit_offset_and_refunds(lease: Lease, rental_account: Account) -> None:
    day = date(2026, 1, 2)
    record_payment(
        lease, day=day, amount=0, deposit_amount=3_600_000, account_id=rental_account.pk, today=day
    )
    pay_monthly(lease, rental_account, range(1, 10), 1_800_000)
    ensure_charges(lease, TODAY)
    assert lease_balance(lease, TODAY).deposit.held == 3_600_000
    with pytest.raises(ValidationError):
        offset_deposit(lease, day=TODAY, amount=3_700_000)
    offset_deposit(lease, day=TODAY, amount=2_200_000)
    balance = lease_balance(lease, TODAY)
    assert balance.balance == 0 and balance.deposit.held == 1_400_000
    with pytest.raises(ValidationError, match="nejvýš drženou"):
        pay_out(
            lease,
            kind=PaymentKind.DEPOSIT_RETURN,
            day=TODAY,
            amount=1_400_001,
            account_id=rental_account.pk,
            today=TODAY,
        )
    returned = pay_out(
        lease,
        kind=PaymentKind.DEPOSIT_RETURN,
        day=TODAY,
        amount=1_400_000,
        account_id=rental_account.pk,
        today=TODAY,
    )
    assert returned.kind == EntryKind.EXPENSE and returned.category is not None
    assert returned.category.code == CategoryCode.DEPOSIT
    assert lease_balance(lease, TODAY).deposit.held == 0
    # Jistota se do výsledku nepočítá.
    year = result_for(date(2026, 1, 1), date(2026, 12, 31), TODAY)
    assert (year.income_cents, year.expense_cents) == (9 * 1_800_000, 0)
    # Přeplatek z vyúčtování (záporný předpis) a jeho vrácení.
    RentCharge.objects.create(
        lease=lease, kind=ChargeKind.SETTLEMENT, due_date=TODAY, amount_cents=-50_000, manual=True
    )
    assert lease_balance(lease, TODAY).balance == -50_000
    refund = pay_out(
        lease,
        kind=PaymentKind.REFUND,
        day=TODAY,
        amount=50_000,
        account_id=rental_account.pk,
        today=TODAY,
    )
    assert lease_balance(lease, TODAY).balance == 0
    assert refund.category is not None and refund.category.code == CategoryCode.OTHER_EXPENSE


def income(account: Account, amount: int, day: date, **kwargs: object) -> Entry:
    rent = Category.objects.get(code=CategoryCode.RENT)
    values: dict[str, object] = {
        "date": day,
        "kind": EntryKind.INCOME,
        "amount_cents": amount,
        "category": rent,
        "account": account,
        **kwargs,
    }
    return Entry.objects.create(**values)


def test_link_existing_entries(lease: Lease, rental_account: Account) -> None:
    entry = income(rental_account, 5_400_000, date(2026, 1, 3), property=lease.property)
    assert [s.entry for s in suggestions(lease, TODAY)] == [entry]
    link_entry(lease, entry, PaymentKind.DEPOSIT, 3_600_000)
    link_entry(lease, entry, PaymentKind.PAYMENT)  # zbytek 18 000
    assert suggestions(lease, TODAY) == []
    with pytest.raises(ValidationError):
        link_entry(lease, entry, PaymentKind.PAYMENT)
    ensure_charges(lease, TODAY)
    balance = lease_balance(lease, TODAY)
    assert balance.paid == 1_800_000 and balance.deposit.received == 3_600_000
    entry.delete()
    assert not lease.payments.exists()


def test_suggestions_scope(lease: Lease, rental_account: Account) -> None:
    other = Property.objects.create(name="Garáž")
    no_property = income(rental_account, 1_800_000, date(2026, 2, 3))
    near = income(rental_account, 1_850_000, date(2026, 3, 3), property=lease.property)
    income(rental_account, 1_800_000, date(2026, 3, 3), property=other)  # jiný byt
    income(rental_account, 1_800_000, date(2025, 10, 1), property=lease.property)  # moc brzy
    assert [s.entry for s in suggestions(lease, TODAY)] == [no_property, near]
    with pytest.raises(ValidationError, match="jinému bytu"):
        link_entry(lease, Entry.objects.get(property=other), PaymentKind.PAYMENT)
    with pytest.raises(ValidationError, match="jen k nákladu"):
        link_entry(lease, near, PaymentKind.REFUND)


def test_linked_entry_keeps_kind_property_and_amount(lease: Lease, rental_account: Account) -> None:
    (entry,) = record_payment(
        lease,
        day=date(2026, 1, 5),
        amount=1_000_000,
        account_id=rental_account.pk,
        today=date(2026, 1, 5),
    )
    base = EntryInput(
        date=entry.date,
        kind=EntryKind.INCOME,
        amount_cents=1_000_000,
        account_id=rental_account.pk,
        category_id=entry.category_id,
        property_id=lease.property_id,
        note="oprava poznámky",
    )
    update_entry(entry, base)  # poznámka a vyšší částka jsou v pořádku
    update_entry(entry, EntryInput(**{**base.__dict__, "amount_cents": 1_200_000}))
    with pytest.raises(ValidationError) as exc:
        update_entry(entry, EntryInput(**{**base.__dict__, "amount_cents": 999_999}))
    assert "přiřazeno" in str(exc.value)
    with pytest.raises(ValidationError, match="druh nejde"):
        update_entry(
            entry,
            EntryInput(
                date=entry.date,
                kind=EntryKind.DEPOSIT,
                amount_cents=1_000_000,
                account_id=rental_account.pk,
            ),
        )
    with pytest.raises(ValidationError, match="byt nejde"):
        other_code = Category.objects.get(code=CategoryCode.OTHER_INCOME).id
        update_entry(
            entry, EntryInput(**{**base.__dict__, "property_id": None, "category_id": other_code})
        )
