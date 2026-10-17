from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from apps.rentals.services.alerts import rental_alerts

MAX_SHOWN = 5  # víc upozornění v hlavičce stránky nezobrazovat


def alerts(request: HttpRequest) -> dict[str, Any]:
    """Upozornění na všech stránkách (jen přihlášenému); celý seznam je v přehledu."""
    if not request.user.is_authenticated:
        return {}
    items = rental_alerts(timezone.localdate())
    return {
        "rental_alerts": items,
        "rental_alerts_shown": items[:MAX_SHOWN],
        "rental_alerts_more": len(items) - MAX_SHOWN,
    }
