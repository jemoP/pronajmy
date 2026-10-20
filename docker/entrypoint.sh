#!/bin/sh
# Vstupní skript provozního image (ZM-010).
#   web (výchozí)          migrace, při prvním startu účet (v demu demo data), gunicorn
#   init-env --url …       vypíše .env pro provoz (bez databáze)
#   manage <příkaz> …      příkaz manage.py, např. manage createsuperuser
#   demo-reset-loop        demo: každý den ve 03:00 obnoví demo data (seed_demo --reset)
set -e
cd /app

demo_mode() {
  case "${DEMO_MODE:-}" in
    [Tt]rue|1|[Yy]es|[Oo]n) return 0 ;;
    *) return 1 ;;
  esac
}

case "${1:-web}" in
  web)
    python manage.pyc wait_for_db
    python manage.pyc migrate --noinput
    if demo_mode; then
      python manage.pyc seed_demo
    else
      python manage.pyc ensure_admin
    fi
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
  demo-reset-loop)
    demo_mode || { echo "demo-reset-loop běží jen v demu (DEMO_MODE=True)." >&2; exit 1; }
    python manage.pyc wait_for_db --timeout 300
    while true; do
      now=$(date +%s)
      next=$(date -d "today ${DEMO_RESET_TIME:-03:00}" +%s)
      [ "$next" -gt "$now" ] || next=$(date -d "tomorrow ${DEMO_RESET_TIME:-03:00}" +%s)
      echo "Další obnova dema: $(date -d "@$next" '+%d. %m. %Y %H:%M')"
      sleep $((next - now))
      python manage.pyc seed_demo --reset || echo "Obnova dema selhala." >&2
    done
    ;;
  *)
    exec "$@"
    ;;
esac
