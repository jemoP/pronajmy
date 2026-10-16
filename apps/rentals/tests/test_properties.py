from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.money.models import Account, AccountKind
from apps.rentals.models import Property
from apps.rentals.services.properties import (
    PropertyInput,
    format_area,
    parse_area,
    save_property,
)


def test_parse_and_format_area() -> None:
    assert parse_area("54,5") == Decimal("54.5")
    assert parse_area("54.5 m²") == Decimal("54.5")
    assert parse_area("") is None
    assert format_area(Decimal("54.0")) == "54" and format_area(Decimal("54.5")) == "54,5"
    with pytest.raises(ValueError, match="plochu"):
        parse_area("54,55")


def test_save_property(db: None) -> None:
    account = Account.objects.create(name="Fio", kind=AccountKind.BANK, active=False)
    flat = save_property(None, PropertyInput(" Byt 1 ", layout="2+kk"))
    assert flat.name == "Byt 1"
    with pytest.raises(ValidationError, match="už existuje"):
        save_property(None, PropertyInput("byt 1"))
    with pytest.raises(ValidationError, match="neaktivní"):
        save_property(flat, PropertyInput("Byt 1", account_id=account.id))


def test_property_pages(auth_client: Client, db: None) -> None:
    assert auth_client.get("/properties").status_code == 200
    response = auth_client.post(
        "/properties/new",
        {"name": "Byt Brno", "address": "Údolní 1", "floor_area": "54,5", "active": "on"},
    )
    assert response.status_code == 302
    flat = Property.objects.get()
    assert flat.floor_area == Decimal("54.5")
    page = auth_client.get("/properties").content.decode()
    assert "Byt Brno" in page and "54,5 m²" in page
    page = auth_client.post(
        f"/properties/{flat.id}/edit", {"name": "Byt Brno", "floor_area": "x"}
    ).content.decode()
    assert "Zadej plochu" in page


def test_property_pages_require_login(client: Client, db: None) -> None:
    for url in ("/properties", "/properties/new"):
        assert client.get(url)["Location"].startswith("/login/")
