from datetime import date

import pytest

from apps.money.models import Account, AccountKind, Category, CategoryCode, Entry, EntryKind
from apps.money.services.entries import EntryInput, create_entry
from apps.rentals.models import Property

TODAY = date(2026, 10, 16)


def category(code: CategoryCode) -> Category:
    return Category.objects.get(code=code)


@pytest.fixture
def bank(db: None) -> Account:
    return Account.objects.create(
        name="Fio pronájmy",
        kind=AccountKind.BANK,
        bank_code="2010",
        account_number="2501234567",
        opening_balance_cents=1_000_000,
    )


@pytest.fixture
def cash(db: None) -> Account:
    return Account.objects.create(name="Pokladna", kind=AccountKind.CASH)


@pytest.fixture
def flat(bank: Account) -> Property:
    return Property.objects.create(name="Byt Brno 2+kk", account=bank)


def add(
    kind: EntryKind,
    amount_cents: int,
    account: Account,
    *,
    day: date = TODAY,
    code: CategoryCode | None = None,
    prop: Property | None = None,
    to_account: Account | None = None,
    note: str = "",
) -> Entry:
    return create_entry(
        EntryInput(
            date=day,
            kind=kind,
            amount_cents=amount_cents,
            account_id=account.id,
            to_account_id=to_account.id if to_account else None,
            category_id=category(code).id if code else None,
            property_id=prop.id if prop else None,
            note=note,
        )
    )
