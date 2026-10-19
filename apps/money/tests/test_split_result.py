"""Oddělený výsledek nájmu a služeb (ZM-008)."""

from datetime import date

from django.test import Client

from apps.money.models import Account, Category, CategoryCode, CategoryKind, EntryKind
from apps.money.services.entries import result_for, split_result_for
from apps.rentals.models import Property
from apps.rentals.services.services_report import services_report

from .conftest import TODAY, add, category

YEAR = (date(2026, 1, 1), date(2026, 12, 31))


def test_default_service_flags(db: None) -> None:
    service = {
        CategoryCode.SERVICES,
        CategoryCode.SETTLEMENT,
        CategoryCode.UTILITIES,
        CategoryCode.ELECTRICITY,
        CategoryCode.GAS,
        CategoryCode.WATER_COLD,
        CategoryCode.WATER_HOT,
        CategoryCode.HEATING,
    }
    for c in Category.objects.exclude(code__isnull=True):
        assert c.is_service == (c.code in service), c.code
    assert not category(CategoryCode.HOA_FUND).is_service  # fond oprav patří do nájmu


def fill(bank: Account, flat: Property) -> Category:
    lift = Category.objects.create(name="Výtah", kind=CategoryKind.EXPENSE, is_service=True)
    add(EntryKind.INCOME, 1_500_000, bank, day=date(2026, 3, 5), code=CategoryCode.RENT, prop=flat)
    add(
        EntryKind.INCOME, 300_000, bank, day=date(2026, 3, 5), code=CategoryCode.SERVICES, prop=flat
    )
    add(
        EntryKind.EXPENSE,
        50_000,
        bank,
        day=date(2026, 4, 1),
        code=CategoryCode.SETTLEMENT,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE,
        200_000,
        bank,
        day=date(2026, 3, 20),
        code=CategoryCode.HEATING,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE,
        120_000,
        bank,
        day=date(2026, 3, 25),
        code=CategoryCode.HOA_FUND,
        prop=flat,
    )
    entry = add(
        EntryKind.EXPENSE, 10_000, bank, day=date(2026, 3, 25), code=CategoryCode.FEES, prop=flat
    )
    entry.category = lift
    entry.save()
    return lift


def test_split_result(bank: Account, flat: Property) -> None:
    fill(bank, flat)
    split = split_result_for(*YEAR, TODAY)
    assert (split.rent.income_cents, split.rent.expense_cents) == (1_500_000, 120_000)
    assert (split.services.income_cents, split.services.expense_cents) == (250_000, 210_000)
    assert split.services.profit_cents == 40_000  # zálohy pokryly náklady
    assert split.total == result_for(*YEAR, TODAY)  # celkem beze změny


def test_custom_service_category_in_services_report(bank: Account, flat: Property) -> None:
    lift = fill(bank, flat)
    report = services_report(2026, TODAY, flat.pk)
    names = [c.name for c in report.columns]
    assert names[:5] == ["Elektřina", "Plyn", "Studená voda", "Teplá voda", "Vytápění"]
    assert names[-1] == lift.name  # vlastní služba na konci
    march = report.months[2]
    assert march.costs[names.index("Vytápění")] == 200_000
    assert march.costs[names.index("Výtah")] == 10_000
    assert (report.total.advances, report.total.settlement) == (300_000, -50_000)


def test_pages_show_split(auth_client: Client, bank: Account, flat: Property) -> None:
    fill(bank, flat)
    overview = auth_client.get("/").content.decode()
    assert "Zisk z nájmu" in overview and "Rozdíl služeb" in overview
    report = auth_client.get("/report?year=2026").content.decode()
    assert "Náklady nájmu (mimo služby)" in report and "Rozdíl služeb" in report
    assert "zálohy pokryly náklady" in report and "Příjmy z nájmu a náklady nájmu" in report
    card = auth_client.get(f"/properties/{flat.pk}").content.decode()
    assert "zisk z nájmu" in card and "rozdíl služeb" in card


def test_category_service_flag_in_ui(auth_client: Client, db: None) -> None:
    hoa = category(CategoryCode.HOA_FUND)
    assert "Skupina" in auth_client.get("/categories").content.decode()
    auth_client.post(
        f"/categories/{hoa.pk}/edit",
        {
            "name": hoa.name,
            "kind": "EXPENSE",
            "sort": "150",
            "active": "on",
            "taxable": "on",
            "is_service": "on",
        },
    )
    hoa.refresh_from_db()
    assert hoa.is_service and hoa.taxable
