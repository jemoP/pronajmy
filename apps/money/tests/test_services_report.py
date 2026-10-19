"""Náklady na energie, přehled služeb a hromadná změna účelu (ZM-007)."""

import csv
import io
from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.money.models import Account, Category, CategoryCode, CategoryKind, Entry, EntryKind
from apps.money.services.entries import recategorize
from apps.rentals.models import Property
from apps.rentals.services.services_report import services_report

from .conftest import TODAY, add, category


def test_energy_categories(db: None) -> None:
    utilities = category(CategoryCode.UTILITIES)
    for code, name in (
        (CategoryCode.ELECTRICITY, "Elektřina"),
        (CategoryCode.GAS, "Plyn"),
        (CategoryCode.WATER_COLD, "Studená voda"),
        (CategoryCode.WATER_HOT, "Teplá voda"),
        (CategoryCode.HEATING, "Vytápění"),
    ):
        energy = category(code)
        assert (energy.name, energy.kind, energy.taxable) == (name, CategoryKind.EXPENSE, False)
        assert energy.sort > utilities.sort


def fill(bank: Account, flat: Property) -> Property:
    other = Property.objects.create(name="Garsoniéra")
    add(
        EntryKind.EXPENSE,
        150_000,
        bank,
        day=date(2026, 1, 20),
        code=CategoryCode.ELECTRICITY,
        prop=flat,
    )
    add(EntryKind.EXPENSE, 80_000, bank, day=date(2026, 1, 25), code=CategoryCode.GAS, prop=flat)
    add(
        EntryKind.EXPENSE,
        60_000,
        bank,
        day=date(2026, 2, 10),
        code=CategoryCode.WATER_COLD,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE,
        30_000,
        bank,
        day=date(2026, 3, 10),
        code=CategoryCode.UTILITIES,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE,
        99_900,
        bank,
        day=date(2026, 3, 10),
        code=CategoryCode.HEATING,
        prop=other,
    )
    add(EntryKind.EXPENSE, 50_000, bank, day=date(2026, 3, 1), code=CategoryCode.REPAIRS, prop=flat)
    for month in (1, 2, 3):
        add(
            EntryKind.INCOME,
            100_000,
            bank,
            day=date(2026, month, 5),
            code=CategoryCode.SERVICES,
            prop=flat,
        )
    add(
        EntryKind.INCOME,
        20_000,
        bank,
        day=date(2026, 5, 5),
        code=CategoryCode.SETTLEMENT,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE,
        5_000,
        bank,
        day=date(2026, 6, 5),
        code=CategoryCode.SETTLEMENT,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE,
        100_000,
        bank,
        day=date(2025, 1, 20),
        code=CategoryCode.ELECTRICITY,
        prop=flat,
    )
    add(
        EntryKind.EXPENSE, 70_000, bank, day=date(2026, 12, 20), code=CategoryCode.GAS, prop=flat
    )  # plán
    return other


def test_services_report(bank: Account, flat: Property) -> None:
    other = fill(bank, flat)
    report = services_report(2026, TODAY, flat.pk)
    names = [c.name for c in report.columns]
    assert names == ["Elektřina", "Plyn", "Studená voda", "Teplá voda", "Vytápění", "Služby"]
    january = report.months[0]
    assert january.costs == [150_000, 80_000, 0, 0, 0, 0] and january.advances == 100_000
    assert report.months[2].costs[5] == 30_000  # ostatní služby; oprava se nepočítá
    assert report.months[11].total == 0  # plánovaný plyn ne
    total = report.total
    assert total.total == 150_000 + 80_000 + 60_000 + 30_000
    assert (total.advances, total.settlement) == (300_000, 15_000)
    assert total.difference == 300_000 + 15_000 - 320_000
    assert report.previous.costs[0] == 100_000
    assert services_report(2026, TODAY, other.pk).total.costs[4] == 99_900
    assert services_report(2026, TODAY).total.total == 320_000 + 99_900  # všechny byty


def test_services_page_and_export(auth_client: Client, bank: Account, flat: Property) -> None:
    fill(bank, flat)
    html = auth_client.get(f"/report/services?year=2026&property={flat.pk}").content.decode()
    assert "Služby a energie" in html and "Elektřina" in html and "zálohy nepokrývají" in html
    assert 'aria-current="page">Služby a energie' in html
    assert "Výsledek a daně" in auth_client.get("/report").content.decode()
    response = auth_client.get(f"/report/services/export.csv?year=2026&property={flat.pk}")
    assert "sluzby-2026.csv" in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:3] == ["Měsíc", "Elektřina", "Plyn"]
    assert rows[1][:3] == ["leden", "1500,00", "800,00"]
    assert rows[13][0] == "Celkem" and rows[14][0] == "Celkem 2025"
    assert auth_client.get("/report/services/export.xlsx").status_code == 200


def test_recategorize(bank: Account, flat: Property, cash: Account) -> None:
    old = [
        add(EntryKind.EXPENSE, 100, bank, code=CategoryCode.UTILITIES, prop=flat),
        add(EntryKind.EXPENSE, 200, bank, code=CategoryCode.UTILITIES, prop=flat),
    ]
    electricity = category(CategoryCode.ELECTRICITY)
    assert recategorize([e.pk for e in old], electricity.pk) == 2
    assert all(
        e.category_id == electricity.pk for e in Entry.objects.filter(pk__in=[e.pk for e in old])
    )
    # Chyba u jednoho pohybu → nezmění se nic.
    transfer = add(EntryKind.TRANSFER, 300, bank, to_account=cash)
    rent = add(EntryKind.INCOME, 400, bank, code=CategoryCode.RENT, prop=flat)
    gas = category(CategoryCode.GAS)
    with pytest.raises(ValidationError) as exc:
        recategorize([old[0].pk, transfer.pk, rent.pk], gas.pk)
    text = " ".join(exc.value.messages)
    assert "převod nemá účel" in text and "je druhu náklad" in text
    assert Entry.objects.get(pk=old[0].pk).category_id == electricity.pk
    with pytest.raises(ValidationError, match="Vyber účel"):
        recategorize([old[0].pk], None)
    with pytest.raises(ValidationError, match="aspoň jeden"):
        recategorize([], gas.pk)


def test_recategorize_via_web(auth_client: Client, bank: Account, flat: Property) -> None:
    entry = add(EntryKind.EXPENSE, 100, bank, code=CategoryCode.UTILITIES, prop=flat)
    page = auth_client.get("/entries").content.decode()
    assert 'data-select-all="bulk"' in page and "Změnit účel označených" in page
    heating = category(CategoryCode.HEATING)
    response = auth_client.post(
        "/entries/recategorize",
        {
            "entries": [str(entry.pk)],
            "category_id": str(heating.pk),
            "back": "/entries?kind=EXPENSE",
        },
    )
    assert response["Location"] == "/entries?kind=EXPENSE"
    assert Entry.objects.get(pk=entry.pk).category == heating
    assert "Účel změněn u pohybů: 1." in auth_client.get(response["Location"]).content.decode()
    assert auth_client.get("/entries/recategorize").status_code == 405


@pytest.mark.parametrize("url", ["/report/services", "/report/services/export.csv"])
def test_requires_login(client: Client, db: None, url: str) -> None:
    assert client.get(url)["Location"].startswith("/login/")


def test_category_lookup_by_name_unchanged(db: None) -> None:
    assert Category.objects.filter(name="Služby", code=CategoryCode.UTILITIES).exists()
