from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.money.models import Account, Category, CategoryCode, CategoryKind, Entry, EntryKind
from apps.money.services.entries import (
    EntryFilter,
    EntryInput,
    list_entries,
    update_entry,
    validate,
)
from apps.rentals.models import Property

from .conftest import TODAY, add, category


def errors_of(**kwargs: object) -> dict[str, str]:
    data = EntryInput(**{"date": TODAY, "amount_cents": 100, **kwargs})  # type: ignore[arg-type]
    return validate(data.normalized())


def test_income_needs_income_or_neutral_category(bank: Account, flat: Property) -> None:
    base = {"kind": EntryKind.INCOME, "account_id": bank.id, "property_id": flat.id}
    assert errors_of(**base)["category_id"] == "Vyber účel."
    repairs = category(CategoryCode.REPAIRS).id
    assert "je druhu náklad" in errors_of(**base, category_id=repairs)["category_id"]
    assert errors_of(**base, category_id=category(CategoryCode.RENT).id) == {}
    assert errors_of(**base, category_id=category(CategoryCode.DEPOSIT).id) == {}


def test_property_required_except_other(bank: Account) -> None:
    rent = errors_of(
        kind=EntryKind.INCOME, account_id=bank.id, category_id=category(CategoryCode.RENT).id
    )
    assert "Vyber byt" in rent["property_id"]
    for kind, code in (
        (EntryKind.INCOME, CategoryCode.OTHER_INCOME),
        (EntryKind.EXPENSE, CategoryCode.OTHER_EXPENSE),
    ):
        assert errors_of(kind=kind, account_id=bank.id, category_id=category(code).id) == {}


def test_transfer_needs_other_account(bank: Account, cash: Account) -> None:
    base = {"kind": EntryKind.TRANSFER, "account_id": bank.id}
    assert "to_account_id" in errors_of(**base)
    assert "různé" in errors_of(**base, to_account_id=bank.id)["to_account_id"]
    assert errors_of(**base, to_account_id=cash.id) == {}


def test_basic_errors(bank: Account) -> None:
    assert errors_of(kind="XXX", account_id=bank.id) == {"kind": "Vyber druh pohybu."}
    errors = errors_of(kind=EntryKind.WITHDRAWAL, account_id=None, amount_cents=0)
    assert errors == {"amount": "Částka musí být větší než 0.", "account_id": "Vyber účet."}


def test_unused_fields_are_dropped(bank: Account, cash: Account, flat: Property) -> None:
    entry = add(EntryKind.WITHDRAWAL, 100, bank, to_account=cash, prop=flat, code=None)
    assert entry.to_account_id is None and entry.property_id is None and entry.category_id is None


def test_inactive_account_kept_on_edit_but_not_new(bank: Account) -> None:
    entry = add(EntryKind.DEPOSIT, 100, bank, note="vklad")
    bank.active = False
    bank.save()
    with pytest.raises(ValidationError, match="neaktivní"):
        add(EntryKind.DEPOSIT, 100, bank)
    data = EntryInput(TODAY, EntryKind.DEPOSIT, 200, bank.id, note="  oprava  ")
    update_entry(entry, data)
    entry.refresh_from_db()
    assert entry.amount_cents == 200 and entry.note == "oprava"


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": EntryKind.INCOME, "amount_cents": 0},
        {"kind": "XXX"},
        {"kind": EntryKind.TRANSFER},
        {"kind": EntryKind.WITHDRAWAL, "to_account": "self"},
        {"kind": EntryKind.WITHDRAWAL, "category": CategoryCode.RENT},
    ],
)
def test_database_constraints(bank: Account, fields: dict[str, object]) -> None:
    values: dict[str, object] = {"date": TODAY, "amount_cents": 100, "account": bank, **fields}
    if values.get("to_account") == "self":
        values["to_account"] = bank
    if isinstance(code := values.pop("category", None), str):
        values["category"] = category(CategoryCode(code))
    with pytest.raises(IntegrityError):
        Entry.objects.create(**values)


def test_filter_and_sums(bank: Account, cash: Account, flat: Property) -> None:
    other = Property.objects.create(name="Garáž")
    add(EntryKind.INCOME, 1_000, bank, code=CategoryCode.RENT, prop=flat, note="Nájem září")
    add(EntryKind.EXPENSE, 300, bank, code=CategoryCode.REPAIRS, prop=other, note="Kohoutek")
    add(EntryKind.TRANSFER, 200, bank, to_account=cash)
    future = TODAY + timedelta(days=5)
    add(EntryKind.INCOME, 5_000, bank, day=future, code=CategoryCode.RENT, prop=flat)

    page = list_entries(EntryFilter(), TODAY)
    assert page.total_count == 4 and page.planned_count == 1
    assert page.sums == {"INCOME": 1_000, "EXPENSE": 300, "TRANSFER": 200}
    assert page.result.profit_cents == 700
    assert page.rows[0].date == future  # řazení od nejnovějšího

    assert list_entries(EntryFilter(property_id=flat.id), TODAY).total_count == 2
    assert list_entries(EntryFilter(account_id=cash.id), TODAY).total_count == 1
    assert list_entries(EntryFilter(text="NAJEM ZARI"), TODAY).total_count == 1
    assert list_entries(EntryFilter(kind=EntryKind.EXPENSE), TODAY).sums == {"EXPENSE": 300}
    by_amount = list_entries(EntryFilter(sort="amount"), TODAY).rows
    assert [e.amount_cents for e in by_amount] == [200, 300, 1_000, 5_000]


def test_custom_category_property_required(bank: Account) -> None:
    own = Category.objects.create(name="Úroky", kind=CategoryKind.INCOME)
    errors = errors_of(kind=EntryKind.INCOME, account_id=bank.id, category_id=own.id)
    assert "property_id" in errors
