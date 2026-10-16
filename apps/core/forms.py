"""Společné pomůcky pro formuláře."""

from typing import Any

from django.core.exceptions import ValidationError


def first_errors(errors: Any) -> dict[str, str]:
    """Chyby formuláře nebo ValidationError → pole: první hláška."""
    if isinstance(errors, ValidationError):
        errors = errors.message_dict
    return {field: messages[0] for field, messages in errors.items()}
