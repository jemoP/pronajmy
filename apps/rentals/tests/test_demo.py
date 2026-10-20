"""Demo se smyšlenými daty (ZM-010, P19)."""

import os
import subprocess
import sys
from datetime import date
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse

from apps.money.models import Category, Entry, EntryKind, PayableDue
from apps.rentals import demo
from apps.rentals.models import Attachment, Lease, LeaseAmendment, LeaseStatus, Property
from apps.rentals.services.alerts import rental_alerts
from apps.rentals.services.charges import lease_balance
from apps.rentals.services.report import account_flows

TODAY = date(2026, 10, 20)


@pytest.fixture
def demo_on(settings: object, monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    settings.DEMO_MODE = True  # type: ignore[attr-defined]
    settings.MEDIA_ROOT = tmp_path  # type: ignore[attr-defined]
    monkeypatch.setattr(demo, "demo_database_ok", lambda: True)


@pytest.fixture
def seeded(db: None, demo_on: None) -> None:
    call_command("seed_demo", today=TODAY, stdout=StringIO())


def test_refuses_without_demo_mode(db: None) -> None:
    with pytest.raises(CommandError, match="DEMO_MODE"):
        call_command("seed_demo")


def test_refuses_on_non_demo_database(db: None, settings: object) -> None:
    settings.DEMO_MODE = True  # type: ignore[attr-defined]
    # Testovací databáze nemá „demo“ v názvu.
    with pytest.raises(CommandError, match="demo"):
        call_command("seed_demo")
    assert not Property.objects.exists()


def test_settings_refuse_demo_mode_on_production_database() -> None:
    environ = {
        "PATH": os.environ["PATH"],
        "DJANGO_SECRET_KEY": "test",
        "DEMO_MODE": "True",
        "DATABASE_URL": "postgres://pronajmy:x@db:5432/pronajmy",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env=environ,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "ImproperlyConfigured" in result.stderr
    environ["DATABASE_URL"] = "postgres://pronajmy:x@db:5432/pronajmy_demo"
    ok = subprocess.run([sys.executable, "-c", "import config.settings"], env=environ)
    assert ok.returncode == 0


def test_demo_data(seeded: None) -> None:
    user = User.objects.get()
    assert user.username == demo.DEMO_USER and user.check_password(demo.DEMO_PASSWORD)
    assert not user.is_staff and not user.is_superuser
    assert Property.objects.count() == 4
    statuses = sorted(Lease.objects.values_list("status", flat=True))
    assert statuses == ["ACTIVE", "ACTIVE", "ACTIVE", "DRAFT", "ENDED"]
    assert Attachment.objects.count() >= 7
    amendments = {
        a.lease.property.name: a for a in LeaseAmendment.objects.select_related("lease__property")
    }
    assert amendments["Lipová 12"].rent_cents == 15_000 * 100
    assert amendments["Na Výsluní 7"].services_cents == 4_600 * 100
    assert amendments["Zahradní 3"].end_date == date(2026, 12, 4)

    # Dluh přesně dva měsíce u smlouvy se spolunájemcem, ostatní smlouvy bez dluhu.
    debts = {
        lease.property.name: lease_balance(lease, TODAY).overdue
        for lease in Lease.objects.exclude(status=LeaseStatus.DRAFT)
    }
    # Od dodatku vyšší zálohy (4 600 Kč).
    assert debts["Na Výsluní 7"] == 2 * (19_500 + 4_600) * 100
    ended = Lease.objects.get(status=LeaseStatus.ENDED)
    balance = lease_balance(ended, TODAY)
    assert balance.balance == 0 and balance.deposit.held == 0
    assert debts["Lipová 12"] == 0 and debts["Zahradní 3"] == 0

    # Upozornění: dluh, končící smlouva, revize za 16 dní, revize po termínu,
    # komunikace po termínu, nezaplacená platba dodavateli.
    texts = " ".join(alert.text for alert in rental_alerts(TODAY))
    for part in ("Nájem po splatnosti", "končí", "za 16 dní", "SVJ Lipová 12"):
        assert part in texts, part
    unpaid = PayableDue.objects.filter(entries__isnull=True, due_date__lt=TODAY, skipped=False)
    assert unpaid.count() == 1

    # Každý z posledních tří let má příjmy i náklady a zůstatek účtu není záporný.
    for year in (TODAY.year - 2, TODAY.year - 1, TODAY.year):
        entries = Entry.objects.filter(date__year=year)
        assert entries.filter(kind=EntryKind.INCOME).exists(), year
        assert entries.filter(kind=EntryKind.EXPENSE).exists(), year
        assert account_flows(year, TODAY).balance_end >= 0, year
    for kind in (EntryKind.WITHDRAWAL, EntryKind.DEPOSIT, EntryKind.TRANSFER):
        assert Entry.objects.filter(kind=kind).exists(), kind


def test_second_run_without_reset_keeps_data(seeded: None) -> None:
    count = Entry.objects.count()
    call_command("seed_demo", today=TODAY, stdout=StringIO())
    assert Entry.objects.count() == count


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_reset_recreates_same_data(demo_on: None) -> None:
    # flush (TRUNCATE) běží v provozu mimo transakci – proto test bez obalující transakce.
    call_command("seed_demo", today=TODAY, stdout=StringIO())
    counts = (Entry.objects.count(), Attachment.objects.count(), Category.objects.count())
    Category.objects.create(name="Návštěvník přidal", kind="EXPENSE")
    call_command("seed_demo", reset=True, today=TODAY, stdout=StringIO())
    assert (Entry.objects.count(), Attachment.objects.count(), Category.objects.count()) == counts
    assert not Category.objects.filter(name="Návštěvník přidal").exists()
    assert User.objects.count() == 1


def test_pages_render(seeded: None, client: Client) -> None:
    client.login(username=demo.DEMO_USER, password=demo.DEMO_PASSWORD)
    lease = Lease.objects.filter(status=LeaseStatus.ACTIVE).first()
    prop = Property.objects.first()
    payable = PayableDue.objects.first()
    assert lease is not None and prop is not None and payable is not None
    names = (
        "rentals:overview rentals:report rentals:report_services rentals:properties"
        " rentals:tenants rentals:repairs rentals:inspections rentals:communications"
        " rentals:inspection_types money:entries money:accounts money:categories money:payables"
    )
    urls = [reverse(name) for name in names.split()]
    urls += [
        reverse("rentals:lease", args=[lease.pk]),
        reverse("rentals:property", args=[prop.pk]),
        reverse("money:payable", args=[payable.payable_id]),
    ]
    for url in urls:
        response = client.get(url, follow=True)
        assert response.status_code == 200, url
        assert "Demo – smyšlená data" in response.content.decode(), url
