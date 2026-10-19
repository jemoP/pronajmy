"""Hromadné mazání pohybů (ZM-009)."""

import csv
import io
from datetime import date
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.money.models import (
    Account,
    AccountKind,
    Category,
    CategoryCode,
    Entry,
    EntryKind,
    Payable,
    PayableDue,
)
from apps.money.services.bulk_delete import delete_entries, delete_summary
from apps.money.services.entries import EntryInput, create_entry, recategorize
from apps.money.services.payables import ItemInput, ensure_dues, pay_dues, save_payable
from apps.rentals.models import Lease, RentPayment, Repair
from apps.rentals.services.charges import ensure_charges, lease_balance
from apps.rentals.services.maintenance import save_repair
from apps.rentals.services.payments import record_payment

TODAY = date(2026, 10, 16)


def entry(kind: EntryKind, amount: int, account: Account, **kwargs: Any) -> Entry:
    return create_entry(
        EntryInput(
            date=date(2026, 10, 1), kind=kind, amount_cents=amount, account_id=account.pk, **kwargs
        )
    )


def test_delete_mixed_kinds(rental_account: Account) -> None:
    cash = Account.objects.create(name="Pokladna", kind=AccountKind.CASH)
    items = [
        entry(EntryKind.WITHDRAWAL, 100_000, rental_account),
        entry(EntryKind.TRANSFER, 50_000, rental_account, to_account_id=cash.pk),
        entry(EntryKind.DEPOSIT, 20_000, rental_account),
    ]
    ids = [e.pk for e in items]
    summary = delete_summary(ids)
    assert summary.count == 3 and not summary.impacts.any
    assert summary.sums_labeled == [
        ("Převod", 50_000),
        ("Výběr do domácnosti", 100_000),
        ("Vklad z domácnosti", 20_000),
    ]
    delete_entries(ids, summary.token)
    assert not Entry.objects.exists()


def test_lease_payment_impact(lease: Lease, rental_account: Account) -> None:
    day = date(2026, 1, 5)
    entries = record_payment(
        lease, day=day, amount=1_800_000, account_id=rental_account.pk, today=day
    )
    ensure_charges(lease, TODAY)
    before = lease_balance(lease, TODAY).balance
    summary = delete_summary([e.pk for e in entries])
    (impact,) = summary.impacts.leases
    assert (impact.lease, impact.count, impact.amount_cents, impact.raises_balance) == (
        lease,
        2,  # nájemné + zálohy
        1_800_000,
        True,
    )
    delete_entries([e.pk for e in entries], summary.token)
    assert not RentPayment.objects.exists()
    assert lease_balance(lease, TODAY).balance == before + 1_800_000


def test_payable_and_repair_impacts(lease: Lease, rental_account: Account) -> None:
    flat = lease.property
    utilities = Category.objects.get(code=CategoryCode.UTILITIES)
    payable = save_payable(
        Payable(name="Elektřina", account=rental_account, due_day=15, valid_from=date(2026, 10, 1)),
        [ItemInput(utilities.pk, flat.pk, 150_000)],
    )
    ensure_dues(TODAY)
    due = payable.dues.get()
    (paid,) = pay_dues([due.pk], day=None, today=TODAY)
    repair = save_repair(
        Repair(property=flat, reported_date=TODAY, title="Zvonek", cost_cents=50_000),
        account_id=rental_account.pk,
        today=TODAY,
    )
    assert repair.entry is not None
    ids = [paid.pk, repair.entry.pk]
    summary = delete_summary(ids)
    assert summary.impacts.reopened_dues == [due] and summary.impacts.repairs == [repair]
    delete_entries(ids, summary.token)
    repair.refresh_from_db()
    assert repair.entry is None and Repair.objects.filter(pk=repair.pk).exists()
    assert not PayableDue.objects.get(pk=due.pk).entries.exists()  # znovu otevřená


def test_changed_entry_rejects_confirmation(rental_account: Account) -> None:
    first = entry(EntryKind.DEPOSIT, 100, rental_account)
    second = entry(EntryKind.DEPOSIT, 200, rental_account)
    summary = delete_summary([first.pk, second.pk])
    first.note = "změna v jiném okně"
    first.save()
    with pytest.raises(ValidationError, match="mezitím změnil"):
        delete_entries([first.pk, second.pk], summary.token)
    second.delete()
    with pytest.raises(ValidationError, match="mezitím změnil"):
        delete_entries([first.pk, second.pk], delete_summary([first.pk]).token)
    assert Entry.objects.filter(pk=first.pk).exists()
    with pytest.raises(ValidationError, match="aspoň jeden"):
        delete_summary([])


def test_bulk_delete_via_web(auth_client: Client, rental_account: Account) -> None:
    items = [entry(EntryKind.DEPOSIT, 100_000, rental_account) for _ in range(2)]
    page = auth_client.get("/entries").content.decode()
    assert 'data-select-all="bulk"' in page and "Smazat označené…" in page
    ids = [str(e.pk) for e in items]
    confirm = auth_client.post(
        "/entries/delete", {"entries": ids, "back": "/entries?kind=DEPOSIT"}
    ).content.decode()
    assert "Smazat 2 pohyby?" in confirm and "Vklad z domácnosti" in confirm
    assert "stáhnout do CSV" in confirm and "Entry" not in confirm
    assert Entry.objects.count() == 2  # zatím nic nesmazáno
    export = auth_client.get(f"/entries/export.csv?ids={','.join(ids)}")
    rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 3
    token = confirm.split('name="token" value="')[1].split('"')[0]
    response = auth_client.post(
        "/entries/delete",
        {"entries": ids, "token": token, "confirm": "1", "back": "/entries?kind=DEPOSIT"},
    )
    assert response["Location"] == "/entries?kind=DEPOSIT" and not Entry.objects.exists()
    assert "Smazáno pohybů: 2" in auth_client.get(response["Location"]).content.decode()
    assert auth_client.get("/entries/delete")["Location"] == "/entries"
    empty = auth_client.post("/entries/delete", {"back": "/entries"})
    assert "Označ aspoň jeden pohyb." in auth_client.get(empty["Location"]).content.decode()


def test_recategorize_with_transfer_selected_changes_nothing(rental_account: Account) -> None:
    cash = Account.objects.create(name="Pokladna", kind=AccountKind.CASH)
    transfer = entry(EntryKind.TRANSFER, 100, rental_account, to_account_id=cash.pk)
    with pytest.raises(ValidationError, match="převod nemá účel"):
        recategorize([transfer.pk], Category.objects.get(code=CategoryCode.GAS).pk)


def test_delete_requires_login(client: Client, db: None) -> None:
    assert client.post("/entries/delete", {"entries": ["1"]})["Location"].startswith("/login/")
