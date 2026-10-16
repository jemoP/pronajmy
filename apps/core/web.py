"""Pomocné funkce pro parametry dotazu a návratové adresy."""

from datetime import date
from urllib.parse import parse_qsl, urlencode


def opt_int(value: object) -> int | None:
    try:
        return int(str(value)) if value not in (None, "") else None
    except ValueError:
        return None


def opt_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value not in (None, "") else None
    except ValueError:
        return None


def safe_back(value: str | None, prefix: str) -> str:
    """Návratová adresa jen v rámci aplikace (žádné přesměrování ven)."""
    if value and value.startswith(prefix) and not value.startswith("//"):
        return value
    return prefix


def with_params(url: str, drop: tuple[str, ...] = (), **params: object) -> str:
    path, _, query = url.partition("?")
    items = {k: v for k, v in parse_qsl(query) if k not in drop and k not in params}
    items.update({k: str(v) for k, v in params.items() if v is not None})
    return f"{path}?{urlencode(items)}" if items else path
