"""Vygeneruje .env pro provoz z hotového image (ZM-010). Nepoužívá Django ani databázi.

docker run --rm ghcr.io/jemop/pronajmy:<verze> init-env --url http://192.168.1.50:8080 > .env
"""

import argparse
import os
import secrets
import sys
from urllib.parse import urlsplit

TEMPLATE = """\
# Pronájmy – provozní nastavení, vygenerováno příkazem init-env. Nikomu neposílej.
# BACKUP_PASSPHRASE a heslo účtu si ulož i mimo tento počítač – bez hesla záloh
# zálohy nejdou obnovit.

# Verze image (aktualizace = změnit číslo, pak docker compose pull && docker compose up -d).
PRONAJMY_VERSION={version}
# Adresa, na které bude aplikace v síti dostupná, a port na hostiteli.
PRONAJMY_URL={url}
PRONAJMY_PORT={port}
# 127.0.0.1 = port jen pro tento počítač (např. přístup jen přes Tailscale).
PRONAJMY_BIND=0.0.0.0
# false = provoz v lokální síti po HTTP.
DJANGO_HTTPS={https}
DJANGO_DEBUG=False
DJANGO_SECRET_KEY={secret_key}

POSTGRES_DB=pronajmy
POSTGRES_USER=pronajmy
POSTGRES_PASSWORD={db_password}

# Účet se založí při prvním startu; heslo pak změň v aplikaci (Změnit heslo).
PRONAJMY_ADMIN_USER={admin_user}
PRONAJMY_ADMIN_PASSWORD={admin_password}

# Zálohy (služba backup).
BACKUP_TIME=02:45
BACKUP_RETENTION_DAYS=30
BACKUP_PASSPHRASE={backup_passphrase}
# Vlastník souborů záloh ve složce backups/ (id -u a id -g uživatele, např. pi = 1000).
BACKUP_UID=1000
BACKUP_GID=1000
"""


def image_version() -> str:
    """Verze image, ze kterého init-env běží (místní build → latest)."""
    version = os.environ.get("APP_VERSION", "")
    return version if version and version[0].isdigit() else "latest"


def render(url: str, admin_user: str = "spravce") -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Adresa musí mít tvar http://IP:PORT, např. http://192.168.1.50:8080.")
    if parts.path not in ("", "/") or parts.query:
        raise ValueError("Adresa nesmí obsahovat cestu – aplikace běží v kořeni (http://IP:PORT).")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return TEMPLATE.format(
        version=image_version(),
        url=f"{parts.scheme}://{parts.netloc}",
        port=port,
        https="true" if parts.scheme == "https" else "false",
        secret_key=secrets.token_urlsafe(50),
        db_password=secrets.token_urlsafe(24),
        admin_user=admin_user,
        admin_password=secrets.token_urlsafe(12),
        backup_passphrase=secrets.token_urlsafe(32),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="init-env", description="Vypíše .env pro provoz.")
    parser.add_argument(
        "--url", required=True, help="adresa aplikace, např. http://192.168.1.50:8080"
    )
    parser.add_argument("--user", default="spravce", help="jméno účtu (výchozí spravce)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(render(args.url, args.user))
    except ValueError as error:
        print(f"Chyba: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
