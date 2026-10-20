#!/bin/sh
# Vstupní skript provozního image (ZM-010).
#   web (výchozí)          migrace, založení účtu při prvním startu, gunicorn
#   init-env --url …       vypíše .env pro provoz (bez databáze)
#   manage <příkaz> …      příkaz manage.py, např. manage createsuperuser
set -e
cd /app

case "${1:-web}" in
  web)
    python manage.pyc wait_for_db
    python manage.pyc migrate --noinput
    python manage.pyc ensure_admin
    exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-2}" --timeout 120 --access-logfile -
    ;;
  init-env)
    shift
    exec python -m config.init_env "$@"
    ;;
  manage)
    shift
    exec python manage.pyc "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
