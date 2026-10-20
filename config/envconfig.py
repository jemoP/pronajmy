"""Odvození nastavení z proměnných prostředí (ZM-010) – čisté funkce kvůli testům."""

from collections.abc import Mapping
from urllib.parse import quote, urlsplit


def database_url(environ: Mapping[str, str]) -> str:
    """DATABASE_URL, nebo adresa poskládaná z POSTGRES_* (heslo se zadává jen jednou)."""
    if url := environ.get("DATABASE_URL"):
        return url
    try:
        name = environ["POSTGRES_DB"]
        user = environ["POSTGRES_USER"]
        password = environ["POSTGRES_PASSWORD"]
    except KeyError as missing:
        raise ValueError(f"Chybí DATABASE_URL nebo {missing.args[0]}.") from None
    host = environ.get("POSTGRES_HOST", "db")
    port = environ.get("POSTGRES_PORT", "5432")
    return f"postgres://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{name}"


def app_url_hosts(app_url: str) -> tuple[list[str], list[str]]:
    """Z adresy aplikace (PRONAJMY_URL) povolený hostitel a důvěryhodný původ pro CSRF."""
    if not app_url:
        return [], []
    parts = urlsplit(app_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"PRONAJMY_URL musí být adresa http(s)://…, ne „{app_url}“.")
    return [parts.hostname], [f"{parts.scheme}://{parts.netloc}"]


def merge_unique(*lists: list[str]) -> list[str]:
    """Spojí seznamy bez duplicit se zachováním pořadí."""
    return list(dict.fromkeys(item for items in lists for item in items))
