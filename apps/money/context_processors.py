from typing import Any

from django.http import HttpRequest

from apps.money.models import AccountKind, CategoryKind, EntryKind


def choices(request: HttpRequest) -> dict[str, Any]:
    return {
        "ENTRY_KINDS": EntryKind.choices,
        "ACCOUNT_KINDS": AccountKind.choices,
        "CATEGORY_KINDS": CategoryKind.choices,
    }
