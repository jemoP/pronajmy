"""Komunikace (P08), opravy (P09) a revize (P10)."""

from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.test import Client

from apps.core.dates import add_months
from apps.money.models import Account, CategoryCode, Entry, EntryKind
from apps.money.services.entries import result_for
from apps.rentals.models import (
    Communication,
    Inspection,
    InspectionPlan,
    InspectionType,
    Lease,
    PaidBy,
    Property,
    Repair,
    RepairStatus,
)
from apps.rentals.services.maintenance import (
    open_follow_ups,
    open_repairs,
    plan_state,
    plan_states,
    save_inspection,
    save_repair,
)

TODAY = date(2026, 10, 16)


def boiler(flat: Property) -> InspectionPlan:
    kind = InspectionType.objects.get(name="Servis plynového kotle")
    return InspectionPlan.objects.create(property=flat, type=kind, device="kotel Vaillant")


def test_default_inspection_types(db: None) -> None:
    assert InspectionType.objects.count() == 6
    assert InspectionType.objects.get(name="Revize elektroinstalace").interval_months == 60
    assert InspectionType.objects.get(name="Servis plynového kotle").remind_days == 30


def test_add_months() -> None:
    assert add_months(date(2025, 11, 1), 12) == date(2026, 11, 1)
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_inspection_due_and_acceptance(flat: Property, rental_account: Account) -> None:
    """Akceptace etapy 3: kotel revidovaný 1. 11. 2025 (12 měsíců) je k 16. 10. 2026
    v okně upozornění „za 16 dní“."""
    plan = boiler(flat)
    assert plan_state(plan, TODAY).due is None
    save_inspection(
        Inspection(plan=plan, done_date=date(2025, 11, 1), result="OK", cost_cents=180_000),
        account_id=rental_account.pk,
    )
    state = plan_state(plan, TODAY)
    assert state.due == date(2026, 11, 1) and state.days_left == 16
    assert state.soon and not state.overdue
    inspection = state.last
    assert inspection is not None and inspection.entry is not None
    entry = inspection.entry
    assert (entry.kind, entry.amount_cents, entry.property_id) == (
        EntryKind.EXPENSE,
        180_000,
        flat.pk,
    )
    assert entry.category is not None and entry.category.code == CategoryCode.INSPECTION


def test_next_due_recomputed_when_done_date_changes(flat: Property) -> None:
    plan = boiler(flat)
    item = save_inspection(
        Inspection(plan=plan, done_date=date(2025, 11, 1), result="OK"), account_id=None
    )
    assert item.next_due_date == date(2026, 11, 1)
    item.done_date = date(2025, 12, 10)  # oprava překlepu, termín zůstal automatický
    save_inspection(item, account_id=None)
    assert item.next_due_date == date(2026, 12, 10)
    item.next_due_date = date(2026, 6, 30)  # ruční termín
    save_inspection(item, account_id=None)
    item.done_date = date(2025, 12, 11)
    save_inspection(item, account_id=None)
    assert item.next_due_date == date(2026, 6, 30)


def test_plan_interval_override_and_order(flat: Property) -> None:
    electro = InspectionPlan.objects.create(
        property=flat,
        type=InspectionType.objects.get(name="Revize elektroinstalace"),
        interval_months=48,
    )
    save_inspection(
        Inspection(plan=electro, done_date=date(2024, 2, 29), result="OK"), account_id=None
    )
    assert plan_state(electro, TODAY).due == date(2028, 2, 29)
    chimney = InspectionPlan.objects.create(
        property=flat,
        type=InspectionType.objects.get(name="Kontrola a čištění spalinové cesty"),
        first_due_date=date(2026, 9, 30),
    )
    InspectionPlan.objects.create(
        property=flat,
        type=InspectionType.objects.get(name="Kontrola hasicího přístroje"),
        active=False,
    )
    states = plan_states(TODAY)
    assert [s.plan for s in states] == [chimney, electro]
    assert states[0].overdue


def test_repair_expense_once_and_lowers_property_result(
    flat: Property, rental_account: Account
) -> None:
    """Akceptace etapy 3: oprava zaplacená z účtu sníží výsledek bytu."""
    repair = Repair(property=flat, reported_date=TODAY, title="Kapající baterie")
    save_repair(repair, account_id=rental_account.pk, today=TODAY)
    assert repair.entry is None  # bez nákladů náklad nevzniká
    assert list(open_repairs(flat)) == [repair]
    repair.status, repair.cost_cents = RepairStatus.DONE, 250_000
    save_repair(repair, account_id=rental_account.pk, today=TODAY)
    assert repair.done_date == TODAY and repair.entry is not None
    assert repair.entry.category is not None
    assert repair.entry.category.code == CategoryCode.REPAIRS
    first = repair.entry_id
    save_repair(repair, account_id=rental_account.pk, today=TODAY)
    assert repair.entry_id == first and Entry.objects.count() == 1
    assert list(open_repairs()) == []
    year = result_for(date(2026, 1, 1), date(2026, 12, 31), TODAY, flat.pk)
    assert (year.expense_cents, year.profit_cents) == (250_000, -250_000)
    tenant_pays = Repair(
        property=flat,
        reported_date=TODAY,
        title="Rozbité okno",
        cost_cents=100,
        paid_by=PaidBy.TENANT,
    )
    save_repair(tenant_pays, account_id=rental_account.pk, today=TODAY)
    assert tenant_pays.entry is None


def test_follow_ups(lease: Lease) -> None:
    item = Communication.objects.create(
        property=lease.property,
        occurred_at="2026-10-10T10:00:00Z",
        channel="PHONE",
        direction="IN",
        subject="Nefunguje zvonek",
        follow_up_date=date(2026, 10, 20),
    )
    assert list(open_follow_ups(lease.property)) == [item]
    item.follow_up_done = True
    item.save()
    assert list(open_follow_ups()) == []


def test_communication_needs_subject(db: None) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        Communication.objects.create(
            occurred_at="2026-10-10T10:00:00Z", channel="PHONE", direction="IN", subject="x"
        )


def test_pages_and_forms(auth_client: Client, lease: Lease, rental_account: Account) -> None:
    flat = lease.property
    html = auth_client.get(f"/properties/{flat.pk}/communications/new").content.decode()
    assert "Jan Nájemník" in html  # předvyplněný nájemník aktuální smlouvy
    response = auth_client.post(
        f"/properties/{flat.pk}/communications/new",
        {
            "occurred_at": "2026-10-15T09:30",
            "channel": "EMAIL",
            "direction": "IN",
            "subject": "Plíseň v koupelně",
            "follow_up_date": "2026-10-25",
        },
    )
    assert response["Location"] == f"/properties/{flat.pk}#komunikace"
    item = Communication.objects.get()
    assert item.property == flat and item.follow_up_date == date(2026, 10, 25)
    auth_client.post(f"/communications/{item.pk}/done", {"back": "/maintenance/communications"})
    item.refresh_from_db()
    assert item.follow_up_done

    auth_client.post(
        f"/properties/{flat.pk}/repairs/new",
        {
            "reported_date": "2026-10-15",
            "title": "Výměna sifonu",
            "status": "DONE",
            "cost_cents": "1 250",
            "paid_by": "OWNER",
            "expense_account": str(rental_account.pk),
        },
    )
    repair = Repair.objects.get()
    assert repair.entry is not None and repair.entry.amount_cents == 125_000
    html = auth_client.get(f"/repairs/{repair.pk}/edit").content.decode()
    assert "Náklad je zapsaný" in html and "Náklad už je zapsaný." in html

    kind = InspectionType.objects.get(name="Servis plynového kotle")
    auth_client.post(
        f"/properties/{flat.pk}/inspection-plans/new", {"type": str(kind.pk), "active": "on"}
    )
    plan = InspectionPlan.objects.get()
    auth_client.post(
        f"/inspection-plans/{plan.pk}/inspections/new", {"done_date": "2025-11-01", "result": "OK"}
    )
    assert plan.inspections.get().next_due_date == date(2026, 11, 1)
    for url, text in (
        ("/maintenance/repairs", "Výměna sifonu"),
        ("/maintenance/inspections", "Zapsat revizi"),
        ("/maintenance/communications", "Plíseň v koupelně"),
        ("/inspection-types", "Revize elektroinstalace"),
    ):
        response = auth_client.get(url)
        assert response.status_code == 200 and text in response.content.decode(), url
    html = auth_client.get(f"/properties/{flat.pk}").content.decode()
    assert "Výměna sifonu" in html and "Servis plynového kotle" in html and "Plíseň" in html


def test_delete_records(auth_client: Client, flat: Property, rental_account: Account) -> None:
    repair = save_repair(
        Repair(property=flat, reported_date=TODAY, title="Okno", cost_cents=100),
        account_id=rental_account.pk,
        today=TODAY,
    )
    response = auth_client.post(f"/repairs/{repair.pk}/delete")
    assert response["Location"] == f"/properties/{flat.pk}#opravy"
    assert not Repair.objects.exists() and Entry.objects.count() == 1  # náklad zůstal
    plan = boiler(flat)
    item = save_inspection(
        Inspection(plan=plan, done_date=date(2025, 11, 1), result="OK"), account_id=None
    )
    auth_client.post(f"/inspection-plans/{plan.pk}/delete")
    assert InspectionPlan.objects.filter(pk=plan.pk).exists()  # má revizi
    auth_client.post(f"/inspections/{item.pk}/delete")
    auth_client.post(f"/inspection-plans/{plan.pk}/delete")
    assert not InspectionPlan.objects.exists()


def test_inspection_type_form(auth_client: Client, db: None) -> None:
    page = auth_client.post(
        "/inspection-types/new", {"name": "Komín", "interval_months": "0", "remind_days": "30"}
    ).content.decode()
    assert "aspoň 1 měsíc" in page
    auth_client.post(
        "/inspection-types/new",
        {"name": "Komín", "interval_months": "6", "remind_days": "14", "active": "on"},
    )
    assert InspectionType.objects.get(name="Komín").interval_months == 6


@pytest.mark.parametrize(
    "url",
    [
        "/maintenance/repairs",
        "/maintenance/inspections",
        "/maintenance/communications",
        "/inspection-types",
        "/properties/1/repairs/new",
        "/attachments/1",
    ],
)
def test_pages_require_login(client: Client, db: None, url: str) -> None:
    assert client.get(url)["Location"].startswith("/login/")


def test_property_card_sections(auth_client: Client, lease: Lease) -> None:
    """Sekce karty bytu jsou sbalovací; rozbalená je jen aktuální smlouva, pohyby jsou na konci."""
    Repair.objects.create(property=lease.property, reported_date=TODAY, title="Zvonek")
    html = auth_client.get(f"/properties/{lease.property_id}").content.decode()
    order = ["smlouva", "smlouvy", "platby", "opravy", "revize", "komunikace", "pohyby"]
    positions = [html.index(f'<details id="{name}"') for name in order]
    assert positions == sorted(positions)
    assert '<details id="smlouva" class="card-section" data-remember open>' in html
    assert '<details id="opravy" class="card-section" data-remember>' in html
    assert "otevřené: 1" in html and "Jan Nájemník" in html
