"""Byty – seznam a uložení (karta bytu přibude v etapě 2)."""

import re
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Count

from apps.core.formatting import NBSP, czech_sort_key
from apps.money.models import Account
from apps.rentals.models import Property

_AREA_RE = re.compile(r"^\d{1,5}(?:[.,]\d)?$")


def parse_area(text: str) -> Decimal | None:
    """Plocha „45,5“ / „45.5 m²“ → Decimal; prázdná → None."""
    cleaned = re.sub(r"\s", "", text.replace(NBSP, "")).removesuffix("m²").removesuffix("m2")
    if not cleaned:
        return None
    if not _AREA_RE.match(cleaned):
        raise ValueError("Zadej plochu v m², např. 54,5.")
    return Decimal(cleaned.replace(",", "."))


def format_area(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.1f}".replace(".", ",").removesuffix(",0")


def list_properties(include_inactive: bool = False) -> list[tuple[Property, int]]:
    """Byty s počtem pohybů; aktivní první, podle české abecedy."""
    qs = Property.objects.select_related("account").annotate(used=Count("entries"))
    if not include_inactive:
        qs = qs.filter(active=True)
    rows = sorted(qs, key=lambda p: (not p.active, czech_sort_key(p.name)))
    return [(p, p.used) for p in rows]


def property_choices(keep_ids: set[int] | None = None) -> list[Property]:
    """Byty do výběru ve formuláři; neaktivní jen pokud jsou už vybrané."""
    keep = keep_ids or set()
    return sorted(
        (p for p in Property.objects.all() if p.active or p.id in keep),
        key=lambda p: czech_sort_key(p.name),
    )


@dataclass(frozen=True)
class PropertyInput:
    name: str
    address: str = ""
    unit: str = ""
    layout: str = ""
    floor_area: Decimal | None = None
    account_id: int | None = None
    active: bool = True
    note: str = ""


def save_property(prop: Property | None, data: PropertyInput) -> Property:
    errors: dict[str, str] = {}
    name = data.name.strip()
    if not name:
        errors["name"] = "Zadej název bytu."
    elif Property.objects.filter(name__iexact=name).exclude(pk=prop.pk if prop else 0).exists():
        errors["name"] = f"Byt „{name}“ už existuje."
    if data.account_id is not None:
        account = Account.objects.filter(pk=data.account_id).first()
        if account is None:
            errors["account_id"] = "Účet neexistuje."
        elif not account.active and (prop is None or prop.account_id != data.account_id):
            errors["account_id"] = f"Účet „{account.name}“ je neaktivní."
    if errors:
        raise ValidationError(errors)
    prop = prop or Property()
    prop.name = name
    prop.address = data.address.strip()
    prop.unit = data.unit.strip()
    prop.layout = data.layout.strip()
    prop.floor_area = data.floor_area
    prop.account_id = data.account_id
    prop.active = data.active
    prop.note = data.note.strip()
    prop.save()
    return prop
