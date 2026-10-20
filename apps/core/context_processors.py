from typing import Any

from django.conf import settings
from django.http import HttpRequest


def app_version(request: HttpRequest) -> dict[str, Any]:
    """Verze aplikace do patičky a příznak dema pro pruh a přihlášení (ZM-010)."""
    return {"app_version": settings.APP_VERSION, "demo_mode": settings.DEMO_MODE}
