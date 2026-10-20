#!/bin/sh
# Přepíše VÝVOJOVOU databázi a přílohy (media/) poslední provozní zálohou z backups/.
# Provozní data se tím nemění. Použití: scripts/dev-from-prod.sh [db_….dump.enc]
set -eu
cd "$(dirname "$0")/.."
prod="docker compose --env-file .env.prod -f compose.yml"

db="${1:-$(ls -t backups/db_*.dump.enc 2>/dev/null | head -1)}"
[ -n "$db" ] && [ -f "$db" ] || { echo "Žádná záloha databáze v backups/." >&2; exit 2; }
media="backups/media_${db#backups/db_}"
media="${media%.dump.enc}.tar.enc"
echo "Obnovuji vývojovou DB ze zálohy $db"
$prod exec -T backup /bin/sh /restore.sh dump "/backups/$(basename "$db")" \
    | docker compose -f compose.dev.yml exec -T db sh -c \
        'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner'
if [ -f "$media" ]; then
    echo "Obnovuji přílohy ze zálohy $media"
    find media -mindepth 1 -delete 2>/dev/null || true
    mkdir -p media
    $prod exec -T backup /bin/sh /restore.sh media-dump "/backups/$(basename "$media")" | tar -xf - -C media
else
    echo "Záloha příloh $media neexistuje – přílohy beze změny."
fi
echo "Hotovo."
