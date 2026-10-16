"""Šablonové filtry a tagy Pronájmů (načtené jako builtins – bez {% load %})."""

from typing import Any
from urllib.parse import urlencode

from django import template
from django.http import HttpRequest

from apps.core import formatting

register = template.Library()

register.filter("czk", formatting.format_czk)
register.filter("cz_date", formatting.format_date)
register.filter("amount_input", formatting.format_amount_input)
register.filter("share", formatting.format_share)


@register.filter
def mask(number: str | None, bank_code: str | None = None) -> str:
    return formatting.mask_account_number(number, bank_code)


@register.filter
def change(current: int, previous: int | None) -> str:
    return formatting.format_change(current, previous)


@register.filter
def get(mapping: dict[Any, Any], key: Any) -> Any:
    """Hodnota ze slovníku podle klíče ({{ errors|get:"amount" }})."""
    return mapping.get(key, "") if mapping else ""


@register.filter
def as_str(value: Any) -> str:
    return "" if value is None else str(value)


@register.simple_tag(takes_context=True)
def url_with(context: dict[str, Any], **params: Any) -> str:
    """Aktuální URL se změněnými parametry dotazu (None/"" parametr odebere)."""
    request: HttpRequest = context["request"]
    query = request.GET.dict()
    for key, value in params.items():
        if value is None or value == "":
            query.pop(key, None)
        else:
            query[key] = str(value)
    return f"{request.path}?{urlencode(query)}" if query else request.path
