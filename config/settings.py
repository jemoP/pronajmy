"""Nastavení Djanga. Tajné a provozní hodnoty jen z prostředí (.env)."""

import os
from pathlib import Path

import django_stubs_ext
import environ
from django.core.exceptions import ImproperlyConfigured

from config.envconfig import app_url_hosts, database_url, merge_unique

# Generika modelů a adminu (ModelAdmin[Model]) za běhu – kvůli typové kontrole.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
# Adresa aplikace (např. http://192.168.1.50:8080) doplní povoleného hostitele i původ pro CSRF;
# localhost kvůli kontrole stavu kontejneru (ZM-010).
_app_hosts, _app_origins = app_url_hosts(env.str("PRONAJMY_URL", default=""))
ALLOWED_HOSTS = merge_unique(env("DJANGO_ALLOWED_HOSTS"), _app_hosts, ["localhost"])
CSRF_TRUSTED_ORIGINS = merge_unique(env("DJANGO_CSRF_TRUSTED_ORIGINS"), _app_origins)
# Verze aplikace z buildu image (patička, /health).
APP_VERSION = env.str("APP_VERSION", default="vývoj")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "apps.core",
    "apps.money",
    "apps.rentals",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Bez přihlášení není přístupná žádná stránka (výjimky: login, health).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app_version",
                "apps.money.context_processors.choices",
                "apps.rentals.context_processors.alerts",
            ],
            "builtins": ["apps.core.templatetags.ui", "django.templatetags.static"],
        },
    }
]

DATABASES = {"default": env.db_url_config(database_url(os.environ))}

# Demo se smyšlenými daty (ZM-010): pruh na stránkách, ukázkové přihlášení, příkaz seed_demo.
# Pojistka: demo nikdy nepoběží nad provozní databází.
DEMO_MODE = env.bool("DEMO_MODE", default=False)
if DEMO_MODE and "demo" not in str(DATABASES["default"]["NAME"]).lower():
    raise ImproperlyConfigured("DEMO_MODE=True smí běžet jen nad databází s „demo“ v názvu.")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "cs"
LANGUAGES = [("cs", "Čeština")]
TIME_ZONE = "Europe/Prague"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Přílohy (v .gitignore). Záměrně bez MEDIA_URL – soubory se stahují jen přes
# přihlášený pohled, nikdy přímo z veřejné adresy.
MEDIA_ROOT = env.path("MEDIA_ROOT", default=BASE_DIR / "media")
# Větší nahrávané soubory jdou na disk, ne do paměti.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # jeden uživatel: přihlášení na 30 dní

if not DEBUG:
    # Statické soubory v provozu servíruje WhiteNoise (ve vývoji runserver).
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    # DJANGO_HTTPS=false: provoz v lokální síti po HTTP – cookies bez příznaku Secure,
    # bez HSTS a bez přesměrování, jinak by se přihlášení neudrželo (ZM-010).
    HTTPS = env.bool("DJANGO_HTTPS", default=True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = HTTPS and env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = HTTPS
    CSRF_COOKIE_SECURE = HTTPS
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30 if HTTPS else 0
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Vědomě vypnuté kontroly (provoz za Tailscale): HTTPS ukončuje `tailscale serve`
    # a jiná cesta do aplikace nevede (W008); doména ts.net nepatří nám, takže HSTS
    # pro subdomény ani preload nedává smysl (W005, W021).
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W008", "security.W021"]
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
