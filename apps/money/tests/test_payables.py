"""Předpisy plateb dodavatelům (ZM-006)."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.money.models import (
    Account,
    CategoryCode,
    Entry,
    EntryKind,
    Frequency,
    Payable,
    PayableDue,
    PaymentMethod,
)
from apps.money.services.payables import (
    ItemInput,
    change_from,
    delete_payable,
    ensure_dues,
    forecast,
    open_dues,
    pay_dues,
    payable_alerts,
    save_payable,
    set_due_amount,
    set_skipped,
    wanted_dues,
)
from apps.rentals.models import Property

from .conftest import TODAY, category


def item(code: CategoryCode, amount: int, prop: Property | None, label: str = "") -> ItemInput:
    return ItemInput(category(code).id, prop.pk if prop else None, amount, label)


def make(
    bank: Account,
    items: list[ItemInput],
    *,
    name: str = "Elektřina",
    valid_from: date = date(2026, 7, 1),
    valid_to: date | None = None,
    frequency: int = Frequency.MONTHLY,
    due_day: int = 15,
    auto: bool = False,
) -> Payable:
    payable = Payable(
        name=name,
        supplier="ČEZ",
        method=PaymentMethod.ORDER,
        account=bank,
        frequency_months=frequency,
        due_day=due_day,
        valid_from=valid_from,
        valid_to=valid_to,
        auto=auto,
    )
    return save_payable(payable, items)


def svj(bank: Account, flat: Property, **kwargs: object) -> Payable:
    """SVJ: jedna platba rozepsaná na fond oprav, správu a zálohy na služby."""
    return make(
        bank,
        [
            item(CategoryCode.HOA_FUND, 200_000, flat, "fond oprav"),
            item(CategoryCode.MANAGEMENT, 30_000, flat, "správa"),
            item(CategoryCode.UTILITIES, 250_000, flat, "voda a teplo"),
        ],
        name="SVJ Laštůvkova",
        **kwargs,  # type: ignore[arg-type]
    )


def test_wanted_dues_follow_validity_and_frequency(bank: Account, flat: Property) -> None:
    monthly = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    assert list(wanted_dues(monthly, TODAY).values()) == [
        date(2026, 7, 15),
        date(2026, 8, 15),
        date(2026, 9, 15),
        date(2026, 10, 15),
    ]
    quarterly = make(
        bank,
        [item(CategoryCode.INSURANCE, 300_000, flat)],
        valid_from=date(2026, 1, 1),
        frequency=Frequency.QUARTERLY,
        due_day=31,
    )
    assert list(wanted_dues(quarterly, TODAY).values()) == [
        date(2026, 1, 31),
        date(2026, 4, 30),  # kratší měsíc → poslední den
        date(2026, 7, 31),
        date(2026, 10, 31),  # aktuální měsíc i se splatností v budoucnosti
    ]
    mid_month = make(bank, [item(CategoryCode.UTILITIES, 100, flat)], valid_from=date(2026, 8, 20))
    assert min(wanted_dues(mid_month, TODAY).values()) == date(2026, 9, 15)
    ended = make(bank, [item(CategoryCode.UTILITIES, 100, flat)], valid_to=date(2026, 8, 31))
    assert list(wanted_dues(ended, TODAY)) == [date(2026, 7, 1), date(2026, 8, 1)]


def test_ensure_dues_idempotent_and_shortening(bank: Account, flat: Property) -> None:
    payable = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    ensure_dues(TODAY)
    ensure_dues(TODAY)
    assert payable.dues.count() == 4
    pay_dues([payable.dues.get(period=date(2026, 7, 1)).pk], day=None, today=TODAY)
    payable.valid_to = date(2026, 8, 31)
    payable.save()
    ensure_dues(TODAY)
    assert sorted(d.period.month for d in payable.dues.all()) == [7, 8]


def test_pay_multi_line_due(bank: Account, flat: Property) -> None:
    payable = svj(bank, flat)
    ensure_dues(TODAY)
    september = payable.dues.get(period=date(2026, 9, 1))
    entries = pay_dues([september.pk], day=None, today=TODAY)
    assert [(e.kind, e.amount_cents, e.date) for e in entries] == [
        (EntryKind.EXPENSE, 200_000, date(2026, 9, 15)),
        (EntryKind.EXPENSE, 30_000, date(2026, 9, 15)),
        (EntryKind.EXPENSE, 250_000, date(2026, 9, 15)),
    ]
    assert entries[0].note == "SVJ Laštůvkova 9/2026 – fond oprav"
    assert all(e.property == flat and e.account == bank for e in entries)
    assert {e.category.code for e in entries if e.category} == {
        CategoryCode.HOA_FUND,
        CategoryCode.MANAGEMENT,
        CategoryCode.UTILITIES,
    }
    assert september not in open_dues(TODAY)
    # Smazání nákladů splátku znovu otevře.
    Entry.objects.filter(payable_due=september).delete()
    assert september in open_dues(TODAY)


def test_batch_and_errors(bank: Account, flat: Property) -> None:
    payable = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    ensure_dues(TODAY)
    july, august, september, _ = payable.dues.order_by("period")
    entries = pay_dues([july.pk, august.pk], day=date(2026, 10, 1), today=TODAY)
    assert {e.date for e in entries} == {date(2026, 10, 1)} and len(entries) == 2
    count = Entry.objects.count()
    with pytest.raises(ValidationError, match="není k zaplacení"):
        pay_dues([september.pk, july.pk], day=None, today=TODAY)  # červenec je zaplacený
    with pytest.raises(ValidationError, match="v budoucnosti"):
        pay_dues([september.pk], day=date(2026, 10, 17), today=TODAY)
    set_skipped(september, True)
    with pytest.raises(ValidationError, match="není k zaplacení"):
        pay_dues([september.pk], day=None, today=TODAY)
    assert Entry.objects.count() == count
    with pytest.raises(ValidationError, match="Zaplacenou"):
        set_skipped(july, True)


def test_auto_mode(bank: Account, flat: Property) -> None:
    payable = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)], due_day=31, auto=True)
    ensure_dues(TODAY)
    paid = {d.period.month for d in payable.dues.all() if d.entries.exists()}
    assert paid == {7, 8, 9}  # říjen má splatnost 31. 10. – ještě ne
    assert Entry.objects.get(payable_due__period=date(2026, 7, 1)).date == date(2026, 7, 31)
    ensure_dues(TODAY)
    assert Entry.objects.count() == 3  # idempotentní


def test_auto_mode_failure_stays_open(bank: Account, flat: Property) -> None:
    make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)], auto=True)
    bank.active = False
    bank.save()
    ensure_dues(TODAY)
    assert not Entry.objects.exists() and open_dues(TODAY).count() == 4
    texts = [a.text for a in payable_alerts(TODAY)]
    assert any("Automatický zápis se nepovedl" in t for t in texts)


def test_due_amount_override(bank: Account, flat: Property) -> None:
    single = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    ensure_dues(TODAY)
    due = single.dues.get(period=date(2026, 10, 1))
    set_due_amount(due, 175_000)
    (entry,) = pay_dues([due.pk], day=None, today=TODAY)
    assert entry.amount_cents == 175_000
    multi = svj(bank, flat)
    ensure_dues(TODAY)
    with pytest.raises(ValidationError, match="jedním řádkem"):
        set_due_amount(multi.dues.first(), 100)  # type: ignore[arg-type]


def test_change_from_date(bank: Account, flat: Property) -> None:
    old = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    ensure_dues(TODAY)
    pay_dues([old.dues.get(period=date(2026, 7, 1)).pk], day=None, today=TODAY)
    new = change_from(old, date(2026, 9, 1))
    old.refresh_from_db()
    assert old.valid_to == date(2026, 8, 31) and new.valid_from == date(2026, 9, 1)
    assert new.previous == old and new.items.get().amount_cents == 150_000
    assert sorted(d.period.month for d in old.dues.all()) == [7, 8]
    ensure_dues(TODAY)
    assert sorted(d.period.month for d in new.dues.all()) == [9, 10]
    with pytest.raises(ValidationError):
        change_from(new, date(2026, 9, 1))  # ne v den začátku


def test_delete_only_without_paid(bank: Account, flat: Property) -> None:
    payable = make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    ensure_dues(TODAY)
    pay_dues([payable.dues.first().pk], day=None, today=TODAY)  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="zaplacené"):
        delete_payable(payable)
    other = make(bank, [item(CategoryCode.UTILITIES, 100, flat)], name="Plyn")
    ensure_dues(TODAY)
    delete_payable(other)
    assert not Payable.objects.filter(pk=other.pk).exists()


def test_item_validation(bank: Account, flat: Property) -> None:
    with pytest.raises(ValidationError) as exc:
        make(bank, [])
    assert "items" in exc.value.message_dict
    with pytest.raises(ValidationError) as exc:
        make(bank, [item(CategoryCode.RENT, 100, flat)])  # účel druhu příjem
    assert "není náklad" in exc.value.message_dict["item_0"][0]
    with pytest.raises(ValidationError) as exc:
        make(bank, [item(CategoryCode.UTILITIES, 100, None)])
    assert "Vyber byt" in exc.value.message_dict["item_0"][0]
    make(bank, [item(CategoryCode.OTHER_EXPENSE, 100, None)])  # ostatní náklady bez bytu


def test_alerts(bank: Account, flat: Property) -> None:
    make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)], name="Plyn")
    make(bank, [item(CategoryCode.UTILITIES, 100, flat)], name="Voda", valid_to=date(2026, 11, 30))
    make(
        bank,
        [item(CategoryCode.UTILITIES, 100, flat)],
        name="Inkaso",
        auto=True,
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 10, 1),
    )
    ensure_dues(TODAY)
    texts = [(a.level, a.text) for a in payable_alerts(TODAY)]
    assert any(level == "over" and "Nezaplaceno dodavateli: Plyn 9/2026" in t for level, t in texts)
    assert ("warning", "Předpis platby Voda končí 30. 11. 2026 (za 45 dní).") in texts
    assert any("Inkaso skončil 1. 10. 2026 – zruš příkaz" in t for _, t in texts)


def test_forecast(bank: Account, flat: Property) -> None:
    make(bank, [item(CategoryCode.UTILITIES, 150_000, flat)])
    make(
        bank,
        [item(CategoryCode.INSURANCE, 600_000, flat)],
        name="Pojištění",
        valid_from=date(2026, 1, 1),
        frequency=Frequency.YEARLY,
    )
    months = forecast(TODAY)
    assert months[0].month == date(2026, 11, 1) and len(months) == 12
    january = next(m for m in months if m.month == date(2027, 1, 1))
    assert january.total == 150_000 + 600_000


def test_pages(auth_client: Client, bank: Account, flat: Property) -> None:
    hoa, utilities = category(CategoryCode.HOA_FUND), category(CategoryCode.UTILITIES)
    response = auth_client.post(
        "/payables/new",
        {
            "name": "SVJ",
            "supplier": "SVJ Laštůvkova",
            "method": "STANDING",
            "account": str(bank.pk),
            "frequency_months": "1",
            "due_day": "20",
            "valid_from": "2026-09-01",
            "supplier_account": "123456789",
            "bank_code": "0800",
            "item_count": "6",
            "item_category_0": str(hoa.pk),
            "item_property_0": str(flat.pk),
            "item_amount_0": "2 000",
            "item_label_0": "fond oprav",
            "item_category_1": str(utilities.pk),
            "item_property_1": str(flat.pk),
            "item_amount_1": "2 500,50",
        },
    )
    payable = Payable.objects.get()
    assert response["Location"] == f"/payables/{payable.pk}"
    assert [i.amount_cents for i in payable.items.order_by("id")] == [200_000, 250_050]
    assert payable.dues.count() == 2  # září a říjen
    detail = auth_client.get(f"/payables/{payable.pk}").content.decode()
    assert "****6789/0800" in detail and "123456789" not in detail
    page = auth_client.get("/payables").content.decode()
    assert "K zaplacení (2" in page and "Výhled na 12 měsíců" in page
    due = PayableDue.objects.get(period=date(2026, 9, 1))
    response = auth_client.post(
        "/payables/pay", {"date_mode": "due", "single": str(due.pk), "back": "/payables"}
    )
    assert response["Location"] == "/payables" and Entry.objects.count() == 2
    card = auth_client.get(f"/properties/{flat.pk}").content.decode()
    assert "Platby dodavatelům" in card and "fond oprav" in card
    assert "Platby" in auth_client.get("/").content.decode()  # v navigaci
    # Chybný rozpis se vrátí s chybou u řádku.
    page = auth_client.post(
        "/payables/new",
        {
            "name": "X",
            "method": "ORDER",
            "account": str(bank.pk),
            "frequency_months": "1",
            "due_day": "15",
            "valid_from": "2026-09-01",
            "item_count": "6",
            "item_category_0": str(hoa.pk),
            "item_amount_0": "abc",
        },
    ).content.decode()
    assert "Řádek 1:" in page and Payable.objects.count() == 1
    assert auth_client.get("/payables/pay")["Location"] == "/payables"


@pytest.mark.parametrize("url", ["/payables", "/payables/new", "/payables/1"])
def test_pages_require_login(client: Client, db: None, url: str) -> None:
    assert client.get(url)["Location"].startswith("/login/")
