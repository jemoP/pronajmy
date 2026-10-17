"""Přílohy: PDF, JPG a PNG do 20 MB. Typ se určuje podle obsahu souboru,
ne podle přípony; soubor se ukládá pod náhodným jménem a stahuje jen přihlášený."""

from typing import Any

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models

from apps.rentals.models import ATTACHMENT_OWNERS, Attachment

MAX_SIZE = 20 * 1024 * 1024
# Začátek souboru → MIME typ.
SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def detect_type(head: bytes) -> str | None:
    return next((mime for magic, mime in SIGNATURES if head.startswith(magic)), None)


def add_attachment(
    owner_field: str, owner: models.Model, upload: UploadedFile[bytes]
) -> Attachment:
    if owner_field not in ATTACHMENT_OWNERS:
        raise ValidationError({"file": "Neplatný záznam pro přílohu."})
    size = upload.size or 0
    if size > MAX_SIZE:
        raise ValidationError({"file": "Soubor je větší než 20 MB."})
    if size == 0:
        raise ValidationError({"file": "Soubor je prázdný."})
    upload.seek(0)
    content_type = detect_type(upload.read(16))
    upload.seek(0)
    if content_type is None:
        raise ValidationError({"file": "Povolené jsou jen soubory PDF, JPG a PNG."})
    name = (upload.name or "priloha").replace("\\", "/").rsplit("/", 1)[-1][:255]
    attachment = Attachment(
        original_name=name, content_type=content_type, size=size, **{owner_field: owner}
    )
    attachment.file.save(name, upload, save=False)
    attachment.save()
    return attachment


def delete_file(attachment: Attachment) -> None:
    """Smaže soubor z úložiště (volá se po smazání záznamu, i kaskádou)."""
    if attachment.file and attachment.file.name:
        attachment.file.storage.delete(attachment.file.name)


def owner_of(attachment: Attachment) -> tuple[str, models.Model]:
    for field in ATTACHMENT_OWNERS:
        owner = getattr(attachment, field)
        if owner is not None:
            return field, owner
    raise ValueError("Příloha bez záznamu")


def attachments_block(owner: str, obj: models.Model) -> dict[str, Any]:
    """Kontext pro includes/attachments.html."""
    return {
        "owner": owner,
        "id": obj.pk,
        "items": Attachment.objects.filter(**{owner: obj}).order_by("uploaded_at"),
    }
