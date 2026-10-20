"""Vygeneruje .env pro provoz z hotového image (ZM-010). Nepoužívá Django ani databázi.

docker run --rm --network host ghcr.io/jemop/pronajmy:<verze> init-env \
    --uid "$(id -u)" --gid "$(id -g)" > .env

S --network host zjistí adresu počítače v síti sám; --url ji přepíše (např. https://… pro
Tailscale). Hlášky jdou na stderr, do .env jen nastavení.
"""

import argparse
import ipaddress
import os
import secrets
import socket
import sys
from urllib.parse import urlsplit

DEFAULT_PORT = 8080
# Vnitřní sítě Dockeru – adresa z nich není adresa počítače v domácí síti.
DOCKER_NETWORK = ipaddress.ip_network("172.16.0.0/12")

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
# Vlastník souborů záloh ve složce backups/ (id -u a id -g uživatele).
BACKUP_UID={uid}
BACKUP_GID={gid}
"""


def image_version() -> str:
    """Verze image, ze kterého init-env běží (místní build → latest)."""
    version = os.environ.get("APP_VERSION", "")
    return version if version and version[0].isdigit() else "latest"


def detect_ip() -> str | None:
    """Adresa, přes kterou počítač komunikuje do sítě (bez odeslání paketu); None, když
    ji nejde zjistit nebo jde o vnitřní síť Dockeru (spuštění bez --network host)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # dokumentační adresa, nic se neposílá
            address = ipaddress.ip_address(sock.getsockname()[0])
    except OSError:
        return None
    if address.is_loopback or address in DOCKER_NETWORK:
        return None
    return str(address)


def address_warning(url: str, detected: str | None) -> str | None:
    """Upozornění, když --url míří na jinou IP adresu, než má tento počítač."""
    host = urlsplit(url.strip()).hostname or ""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None  # jméno (např. *.ts.net) se neověřuje
    if detected and host != detected:
        return (
            f"Pozor: adresa {host} z --url není adresa tohoto počítače ({detected})."
            " Aplikace by na ní odpovídala chybou Bad Request (400)."
        )
    return None


def render(url: str, admin_user: str = "spravce", uid: int = 1000, gid: int = 1000) -> str:
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
        uid=uid,
        gid=gid,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="init-env", description="Vypíše .env pro provoz.")
    parser.add_argument(
        "--url",
        help="adresa aplikace, např. http://192.168.1.50:8080 (výchozí: zjištěná IP adresa"
        f" počítače a port {DEFAULT_PORT}, vyžaduje --network host)",
    )
    parser.add_argument("--user", default="spravce", help="jméno účtu (výchozí spravce)")
    parser.add_argument("--uid", type=int, default=1000, help="vlastník záloh: id -u")
    parser.add_argument("--gid", type=int, default=1000, help="skupina záloh: id -g")
    args = parser.parse_args(argv)
    detected = detect_ip()
    url = args.url
    if not url:
        if detected is None:
            print(
                "Chyba: adresu počítače nejde zjistit. Spusť příkaz s --network host,"
                " nebo zadej adresu: --url http://<IP adresa>:8080 (IP adresu vypíše"
                " hostname -I).",
                file=sys.stderr,
            )
            return 2
        url = f"http://{detected}:{DEFAULT_PORT}"
    try:
        text = render(url, args.user, args.uid, args.gid)
    except ValueError as error:
        print(f"Chyba: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(text)
    if warning := address_warning(url, detected):
        print(warning, file=sys.stderr)
    print(f"Aplikace bude dostupná na {url.rstrip('/')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
