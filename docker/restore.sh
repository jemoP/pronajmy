#!/bin/sh
# Kontrola a obnova záloh (P15). Spouští se v kontejneru backup:
#   restore.sh check <db_….dump.enc>          obnoví do dočasné DB, vypíše počty vedle provozních, DB smaže
#   restore.sh restore <db_….dump.enc>        PŘEPÍŠE provozní DB (předtím zastav službu web)
#   restore.sh dump <db_….dump.enc>           dešifrovaný výpis na stdout
#   restore.sh media-check <media_….tar.enc>  počet souborů v záloze a přílohy z DB, které v ní chybí
#   restore.sh media-restore <media_….tar.enc> PŘEPÍŠE přílohy (předtím zastav službu web)
#   restore.sh media-dump <media_….tar.enc>   dešifrovaný tar na stdout
set -eu
set -o pipefail

: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE musí být nastavené}"
export PGPASSWORD="$POSTGRES_PASSWORD"
# Bez hlášek typu NOTICE (DROP … IF EXISTS).
export PGOPTIONS="--client-min-messages=warning"
DB_HOST="${POSTGRES_HOST:-db}"
MEDIA=/media
# Přílohy patří uživateli aplikace v image web (UID 1000).
APP_OWNER=1000:1000
mode="${1:-}"
file="${2:-}"
[ -f "$file" ] || { echo "Soubor zálohy '$file' neexistuje." >&2; exit 2; }

decrypt() {
    openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$file"
}

sql() {
    psql -h "$DB_HOST" -U "$POSTGRES_USER" -d "$1" -At -F ' | ' -c "$2"
}

summary() {
    sql "$1" "SELECT 'pohybů', count(*), 'součet haléřů', coalesce(sum(amount_cents), 0) FROM entry;
              SELECT 'bytů', count(*), 'smluv', (SELECT count(*) FROM lease) FROM property;
              SELECT 'plateb', count(*), 'příloh', (SELECT count(*) FROM attachment) FROM rent_payment;
              SELECT 'uživatelů', count(*) FROM auth_user;"
}

case "$mode" in
    check)
        target="pronajmy_restore_check"
        sql "$POSTGRES_DB" "DROP DATABASE IF EXISTS $target" >/dev/null
        sql "$POSTGRES_DB" "CREATE DATABASE $target" >/dev/null
        decrypt | pg_restore -h "$DB_HOST" -U "$POSTGRES_USER" -d "$target" --no-owner
        echo "== záloha $file =="; summary "$target"
        echo "== provozní DB =="; summary "$POSTGRES_DB"
        sql "$POSTGRES_DB" "DROP DATABASE $target" >/dev/null
        ;;
    restore)
        decrypt | pg_restore -h "$DB_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner
        echo "Obnoveno z $file:"; summary "$POSTGRES_DB"
        ;;
    dump)
        decrypt
        ;;
    media-check)
        list=$(mktemp)
        trap 'rm -f "$list"' EXIT
        decrypt | tar -tf - | sed 's|^\./||' | grep -v -e '/$' -e '^$' > "$list" || true
        echo "Souborů v záloze: $(wc -l < "$list")"
        missing=$(sql "$POSTGRES_DB" "SELECT file FROM attachment ORDER BY file" | grep -Fxv -f "$list" || true)
        if [ -n "$missing" ]; then
            echo "Přílohy z provozní DB, které v záloze chybí: $(echo "$missing" | wc -l)"
            exit 1
        fi
        echo "Všechny přílohy z provozní DB ($(sql "$POSTGRES_DB" "SELECT count(*) FROM attachment")) jsou v záloze."
        ;;
    media-restore)
        find "$MEDIA" -mindepth 1 -delete
        decrypt | tar -xf - -C "$MEDIA"
        chown -R "$APP_OWNER" "$MEDIA"
        echo "Přílohy obnoveny z $file (souborů: $(find "$MEDIA" -type f | wc -l))."
        ;;
    media-dump)
        decrypt
        ;;
    *)
        echo "Použití: restore.sh check|restore|dump|media-check|media-restore|media-dump <soubor>" >&2
        exit 2
        ;;
esac
