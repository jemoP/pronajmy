"""Přílohy: typ podle obsahu, limit, stažení jen přihlášeným, mazání souborů."""

from pathlib import Path

import pytest
from django.conf import LazySettings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client

from apps.rentals.models import (
    Attachment,
    Communication,
    Inspection,
    InspectionPlan,
    InspectionType,
    Lease,
    LeaseAmendment,
    LeaseStatus,
    Repair,
)
from apps.rentals.services import attachments as service

PDF = b"%PDF-1.7\n%test\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20


@pytest.fixture(autouse=True)
def media(settings: LazySettings, tmp_path: Path) -> Path:
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def test_upload_detects_type_by_content(auth_client: Client, lease: Lease, media: Path) -> None:
    """Akceptace etapy 3: příloha s neplatným obsahem se odmítne."""
    files = [
        SimpleUploadedFile("smlouva.pdf", PDF, content_type="text/html"),
        SimpleUploadedFile("foto.PNG", PNG),
        SimpleUploadedFile("sken.jpg", JPG),
        SimpleUploadedFile("virus.pdf", b"MZ\x90\x00", content_type="application/pdf"),
    ]
    back = f"/leases/{lease.pk}"
    response = auth_client.post(
        "/attachments/upload", {"owner": "lease", "id": str(lease.pk), "back": back, "file": files}
    )
    assert response["Location"] == back
    saved = {a.original_name: a for a in Attachment.objects.all()}
    assert set(saved) == {"smlouva.pdf", "foto.PNG", "sken.jpg"}
    assert saved["smlouva.pdf"].content_type == "application/pdf"
    assert saved["sken.jpg"].content_type == "image/jpeg"
    stored = Path(saved["foto.PNG"].file.path)
    assert stored.parent == media / "rentals" and stored.suffix == ".png"
    assert "foto" not in stored.name  # náhodné jméno souboru
    html = auth_client.get(back, follow=True).content.decode()
    assert "virus.pdf" in html and "Povolené jsou jen soubory PDF, JPG a PNG." in html


def test_size_limit_and_empty(lease: Lease, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Exception, match="prázdný"):
        service.add_attachment("lease", lease, SimpleUploadedFile("nic.pdf", b""))
    monkeypatch.setattr(service, "MAX_SIZE", 10)
    with pytest.raises(Exception, match="20 MB"):
        service.add_attachment("lease", lease, SimpleUploadedFile("velky.pdf", PDF))


def test_download_requires_login(auth_client: Client, lease: Lease) -> None:
    attachment = service.add_attachment("lease", lease, SimpleUploadedFile("s.pdf", PDF))
    url = f"/attachments/{attachment.pk}"
    assert Client().get(url)["Location"].startswith("/login/")
    response = auth_client.get(url)
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["Cache-Control"] == "private, no-store"
    assert b"".join(response.streaming_content) == PDF  # type: ignore[attr-defined]
    assert 's.pdf"' in response["Content-Disposition"]


def test_delete_removes_files(auth_client: Client, lease: Lease) -> None:
    first = service.add_attachment("lease", lease, SimpleUploadedFile("a.pdf", PDF))
    path = Path(first.file.path)
    auth_client.post(f"/attachments/{first.pk}/delete", {"back": "/"})
    assert not path.exists()
    # Kaskáda: smazání návrhu smlouvy smaže i soubory příloh (i u dodatku).
    lease.status = LeaseStatus.DRAFT
    lease.save()
    amendment = LeaseAmendment.objects.get(lease=lease)
    second = service.add_attachment("amendment", amendment, SimpleUploadedFile("b.png", PNG))
    path = Path(second.file.path)
    auth_client.post(f"/leases/{lease.pk}/delete")
    assert not path.exists() and not Attachment.objects.exists()


def test_deleting_record_removes_files(auth_client: Client, lease: Lease) -> None:
    repair = Repair.objects.create(property=lease.property, reported_date="2026-10-01", title="X")
    note = Communication.objects.create(
        property=lease.property,
        occurred_at="2026-10-10T10:00:00Z",
        channel="PHONE",
        direction="IN",
        subject="Y",
    )
    paths = [
        Path(service.add_attachment("repair", repair, SimpleUploadedFile("r.pdf", PDF)).file.path),
        Path(
            service.add_attachment(
                "communication", note, SimpleUploadedFile("c.pdf", PDF)
            ).file.path
        ),
    ]
    auth_client.post(f"/repairs/{repair.pk}/delete")
    auth_client.post(f"/communications/{note.pk}/delete")
    assert not any(p.exists() for p in paths) and not Attachment.objects.exists()


def test_attachment_exactly_one_owner(lease: Lease) -> None:
    values = {"file": "rentals/x.pdf", "original_name": "x.pdf", "content_type": "a", "size": 1}
    amendment = LeaseAmendment.objects.get(lease=lease)
    for owners in ({}, {"lease": lease, "amendment": amendment}):
        with pytest.raises(IntegrityError), transaction.atomic():
            Attachment.objects.create(**values, **owners)
    Attachment.objects.create(lease=lease, **values)


def test_attachment_blocks_on_pages(auth_client: Client, lease: Lease) -> None:
    amendment = LeaseAmendment.objects.get(lease=lease)
    for url in (f"/leases/{lease.pk}", f"/leases/{lease.pk}/amendments/{amendment.pk}/edit"):
        assert "PDF, JPG nebo PNG do 20 MB" in auth_client.get(url).content.decode()
    new_page = auth_client.get(f"/leases/{lease.pk}/amendments/new").content.decode()
    assert "PDF, JPG nebo PNG" not in new_page
    response = auth_client.post("/attachments/upload", {"owner": "nic", "id": "1"})
    assert response.status_code == 404


def test_attachment_badge_in_lists(auth_client: Client, lease: Lease) -> None:
    """Záznam s přílohami má v seznamech příznak 📎 s počtem."""
    flat = lease.property
    amendment = LeaseAmendment.objects.get(lease=lease)
    repair = Repair.objects.create(property=flat, reported_date="2026-10-01", title="Kohoutek")
    note = Communication.objects.create(
        property=flat,
        occurred_at="2026-10-10T10:00:00Z",
        channel="PHONE",
        direction="IN",
        subject="Zvonek",
    )
    plan = InspectionPlan.objects.create(
        property=flat, type=InspectionType.objects.get(name="Servis plynového kotle")
    )
    inspection = Inspection.objects.create(plan=plan, done_date="2025-11-01", result="OK")
    for owner, obj in (
        ("lease", lease),
        ("amendment", amendment),
        ("repair", repair),
        ("communication", note),
        ("inspection", inspection),
    ):
        service.add_attachment(owner, obj, SimpleUploadedFile("a.pdf", PDF))
    service.add_attachment("repair", repair, SimpleUploadedFile("b.png", PNG))

    card = auth_client.get(f"/properties/{flat.pk}").content.decode()
    # smlouva, oprava (2), revize, komunikace
    assert card.count("📎") == 4 and '2<span class="sr-only"> přílohy' in card
    assert "📎" in auth_client.get("/maintenance/repairs").content.decode()
    assert "📎" in auth_client.get("/maintenance/communications").content.decode()
    assert "📎" in auth_client.get("/maintenance/inspections").content.decode()
    lease_page = auth_client.get(f"/leases/{lease.pk}").content.decode()
    assert "📎" in lease_page and '1<span class="sr-only"> příloha' in lease_page
    # Bez příloh příznak není.
    Attachment.objects.all().delete()
    assert "📎" not in auth_client.get(f"/properties/{flat.pk}").content.decode()
