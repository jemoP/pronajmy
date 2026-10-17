"""Akceptace etapy 1: zůstatky a výsledek."""

from datetime import date, timedelta

from apps.money.models import Account, CategoryCode, EntryKind
from apps.money.services.accounts import balances_at, list_accounts
from apps.money.services.entries import Result, result_for
from apps.rentals.models import Property

from .conftest import TODAY, add

YEAR = (date(2026, 1, 1), date(2026, 12, 31))


def result() -> Result:
    return result_for(*YEAR, TODAY)


def balance(account: Account, at: date = TODAY) -> int:
    return balances_at(at)[account.id]


def test_income_increases_and_expense_decreases_balance(bank: Account, flat: Property) -> None:
    add(EntryKind.INCOME, 1_800_000, bank, code=CategoryCode.RENT, prop=flat)
    assert balance(bank) == 1_000_000 + 1_800_000
    add(EntryKind.EXPENSE, 300_000, bank, code=CategoryCode.REPAIRS, prop=flat)
    assert balance(bank) == 1_000_000 + 1_800_000 - 300_000
    assert result() == Result(1_800_000, 300_000)
    assert result().profit_cents == 1_500_000


def test_returned_income_lowers_income(bank: Account, flat: Property) -> None:
    add(EntryKind.INCOME, 1_800_000, bank, code=CategoryCode.RENT, prop=flat)
    add(EntryKind.EXPENSE, 200_000, bank, code=CategoryCode.SETTLEMENT, prop=flat)
    add(EntryKind.EXPENSE, 300_000, bank, code=CategoryCode.REPAIRS, prop=flat)
    assert balance(bank) == 1_000_000 + 1_800_000 - 200_000 - 300_000
    assert result() == Result(1_600_000, 300_000)


def test_withdrawal_lowers_balance_but_not_result(bank: Account, flat: Property) -> None:
    add(EntryKind.INCOME, 1_800_000, bank, code=CategoryCode.RENT, prop=flat)
    before = result()
    add(EntryKind.WITHDRAWAL, 1_000_000, bank)
    assert balance(bank) == 1_000_000 + 1_800_000 - 1_000_000
    assert result() == before


def test_deposit_raises_balance_but_not_result(bank: Account) -> None:
    add(EntryKind.DEPOSIT, 500_000, bank)
    assert balance(bank) == 1_500_000
    assert result() == Result()


def test_transfer_keeps_total(bank: Account, cash: Account) -> None:
    total = sum(balances_at(TODAY).values())
    add(EntryKind.TRANSFER, 200_000, bank, to_account=cash)
    assert balance(bank) == 800_000
    assert balance(cash) == 200_000
    assert sum(balances_at(TODAY).values()) == total
    assert result() == Result()


def test_security_deposit_is_outside_result(bank: Account, flat: Property) -> None:
    add(EntryKind.INCOME, 3_600_000, bank, code=CategoryCode.DEPOSIT, prop=flat)
    add(EntryKind.EXPENSE, 1_000_000, bank, code=CategoryCode.DEPOSIT, prop=flat)
    assert balance(bank) == 1_000_000 + 2_600_000
    assert result() == Result()


def test_planned_entry_counts_only_at_its_date(bank: Account, flat: Property) -> None:
    later = TODAY + timedelta(days=10)
    add(EntryKind.INCOME, 1_800_000, bank, day=later, code=CategoryCode.RENT, prop=flat)
    assert balance(bank) == 1_000_000
    assert balance(bank, later) == 2_800_000
    assert result() == Result()


def test_balance_at_date(bank: Account, flat: Property) -> None:
    add(EntryKind.INCOME, 100_00, bank, day=date(2026, 3, 1), code=CategoryCode.RENT, prop=flat)
    add(EntryKind.INCOME, 200_00, bank, day=date(2026, 4, 1), code=CategoryCode.RENT, prop=flat)
    assert balance(bank, date(2026, 2, 28)) == 1_000_000
    assert balance(bank, date(2026, 3, 1)) == 1_010_000
    assert balance(bank, date(2026, 4, 1)) == 1_030_000


def test_list_accounts_hides_inactive(bank: Account, cash: Account) -> None:
    cash.active = False
    cash.save()
    assert [r.account for r in list_accounts(TODAY)] == [bank]
    assert [r.account for r in list_accounts(TODAY, include_inactive=True)] == [bank, cash]
