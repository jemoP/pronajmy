"""Stránky pronájmů – zatím byty (seznam a formulář, ZM-002)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.forms import first_errors
from apps.core.web import opt_int
from apps.money.services.accounts import account_choices
from apps.rentals.models import Property
from apps.rentals.services.properties import (
    PropertyInput,
    format_area,
    list_properties,
    parse_area,
    save_property,
)

PROPERTY_FIELDS = ("name", "address", "unit", "layout", "floor_area", "account_id", "note")


def properties(request: HttpRequest) -> HttpResponse:
    include_inactive = request.GET.get("inactive") == "1"
    return render(
        request,
        "rentals/properties.html",
        {
            "nav": "properties",
            "rows": list_properties(include_inactive),
            "include_inactive": include_inactive,
        },
    )


def property_values(prop: Property | None) -> dict[str, str]:
    if prop is None:
        return {"active": "on"}
    return {
        "name": prop.name,
        "address": prop.address,
        "unit": prop.unit,
        "layout": prop.layout,
        "floor_area": format_area(prop.floor_area),
        "account_id": str(prop.account_id or ""),
        "active": "on" if prop.active else "",
        "note": prop.note,
    }


def property_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    prop = get_object_or_404(Property, pk=pk) if pk else None
    errors: dict[str, str] = {}
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in (*PROPERTY_FIELDS, "active")}
        try:
            area = parse_area(values["floor_area"])
            save_property(
                prop,
                PropertyInput(
                    name=values["name"],
                    address=values["address"],
                    unit=values["unit"],
                    layout=values["layout"],
                    floor_area=area,
                    account_id=opt_int(values["account_id"]),
                    active=values["active"] == "on",
                    note=values["note"],
                ),
            )
        except ValueError as exc:
            errors = {"floor_area": str(exc)}
        except ValidationError as exc:
            errors = first_errors(exc)
        else:
            messages.success(request, "Byt uložen.")
            return redirect("rentals:properties")
    else:
        values = property_values(prop)
    keep = {i for i in [opt_int(values.get("account_id"))] if i}
    return render(
        request,
        "rentals/property_form.html",
        {
            "nav": "properties",
            "property": prop,
            "values": values,
            "errors": errors,
            "accounts": account_choices(keep),
        },
    )
