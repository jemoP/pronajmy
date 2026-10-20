"""Nastavení a příkazy pro provoz z hotového image (ZM-010)."""

import json
import os
import subprocess
import sys

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from config import init_env
from config.envconfig import app_url_hosts, database_url, merge_unique


def test_database_url_takes_precedence() -> None:
    assert database_url({"DATABASE_URL": "postgres://a:b@c/d", "POSTGRES_DB": "x"}) == (
        "postgres://a:b@c/d"
    )


def test_database_url_from_postgres_vars_escapes_password() -> None:
    url = database_url(
        {"POSTGRES_DB": "pronajmy", "POSTGRES_USER": "pronajmy", "POSTGRES_PASSWORD": "a/b@c:d"}
    )
    assert url == "postgres://pronajmy:a%2Fb%40c%3Ad@db:5432/pronajmy"


def test_database_url_missing_values() -> None:
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        database_url({"POSTGRES_DB": "x", "POSTGRES_USER": "y"})


def test_app_url_hosts() -> None:
    assert app_url_hosts("http://192.168.1.50:8080/") == (
        ["192.168.1.50"],
        ["http://192.168.1.50:8080"],
    )
    assert app_url_hosts("") == ([], [])
    with pytest.raises(ValueError):
        app_url_hosts("192.168.1.50:8080")


def test_merge_unique_keeps_order() -> None:
    assert merge_unique(["a", "b"], ["b", "c"], ["a"]) == ["a", "b", "c"]


def test_init_env_lan_http() -> None:
    text = init_env.render("http://192.168.1.50:8080")
    values = dict(
        line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#")
    )
    assert values["PRONAJMY_URL"] == "http://192.168.1.50:8080"
    assert values["PRONAJMY_PORT"] == "8080"
    assert values["DJANGO_HTTPS"] == "false"
    assert values["DJANGO_DEBUG"] == "False"
    assert values["PRONAJMY_ADMIN_USER"] == "spravce"
    for key in ("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "PRONAJMY_ADMIN_PASSWORD"):
        assert len(values[key]) >= 16, key
    assert len(values["BACKUP_PASSPHRASE"]) >= 32
    # Každé spuštění generuje nová tajemství.
    assert init_env.render("http://192.168.1.50:8080") != text


def test_init_env_rejects_bad_url(capsys: pytest.CaptureFixture[str]) -> None:
    assert init_env.main(["--url", "192.168.1.50"]) == 2
    assert init_env.main(["--url", "http://192.168.1.50/pronajmy"]) == 2
    assert "Chyba" in capsys.readouterr().err


@pytest.mark.django_db
def test_ensure_admin_creates_first_user_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRONAJMY_ADMIN_USER", "spravce")
    monkeypatch.setenv("PRONAJMY_ADMIN_PASSWORD", "tajne-heslo-456")
    call_command("ensure_admin")
    admin = User.objects.get()
    assert admin.is_superuser and admin.check_password("tajne-heslo-456")

    # Další start heslo nepřepíše (uživatel si ho mezitím mohl změnit).
    monkeypatch.setenv("PRONAJMY_ADMIN_PASSWORD", "jine-heslo-789")
    call_command("ensure_admin")
    assert User.objects.get().check_password("tajne-heslo-456")


@pytest.mark.django_db
def test_ensure_admin_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRONAJMY_ADMIN_USER", raising=False)
    monkeypatch.delenv("PRONAJMY_ADMIN_PASSWORD", raising=False)
    call_command("ensure_admin")
    assert not User.objects.exists()


def _prod_settings(**extra: str) -> dict[str, object]:
    """Načte nastavení v samostatném procesu s provozním prostředím."""
    environ = {
        "PATH": os.environ["PATH"],
        "DJANGO_SECRET_KEY": "test",
        "DJANGO_DEBUG": "False",
        "POSTGRES_DB": "pronajmy",
        "POSTGRES_USER": "pronajmy",
        "POSTGRES_PASSWORD": "heslo",
        "PRONAJMY_URL": "http://192.168.1.50:8080",
        **extra,
    }
    code = (
        "import json; from config import settings as s; print(json.dumps({k: getattr(s, k) "
        "for k in ('SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'SECURE_SSL_REDIRECT', "
        "'SECURE_HSTS_SECONDS', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS')}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=environ, capture_output=True, text=True, check=True
    )
    loaded: dict[str, object] = json.loads(result.stdout)
    return loaded


def test_prod_settings_lan_http() -> None:
    settings = _prod_settings(DJANGO_HTTPS="false")
    assert settings["SESSION_COOKIE_SECURE"] is False
    assert settings["CSRF_COOKIE_SECURE"] is False
    assert settings["SECURE_SSL_REDIRECT"] is False
    assert settings["SECURE_HSTS_SECONDS"] == 0
    assert settings["ALLOWED_HOSTS"] == ["192.168.1.50", "localhost"]
    assert settings["CSRF_TRUSTED_ORIGINS"] == ["http://192.168.1.50:8080"]


def test_prod_settings_https_by_default() -> None:
    settings = _prod_settings()
    assert settings["SESSION_COOKIE_SECURE"] is True
    assert settings["CSRF_COOKIE_SECURE"] is True
    assert settings["SECURE_SSL_REDIRECT"] is True
    assert settings["SECURE_HSTS_SECONDS"] == 60 * 60 * 24 * 30
