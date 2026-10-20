#!/bin/sh
# Denní šifrovaná záloha databáze a příloh (P15). „backup.sh now“ = jednorázová záloha.
#   /backups/db_RRRR-MM-DD_HHMM.dump.enc     pg_dump -Fc, AES-256
#   /backups/media_RRRR-MM-DD_HHMM.tar.enc   přílohy (tar), AES-256
set -eu
set -o pipefail

: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE musí být nastavené}"
export PGPASSWORD="$POSTGRES_PASSWORD"
DB_HOST="${POSTGRES_HOST:-db}"
BACKUP_TIME="${BACKUP_TIME:-02:45}"
RETENTION="${BACKUP_RETENTION_DAYS:-30}"
# Vlastník souborů záloh na hostiteli (na Raspberry Pi obvykle uživatel pi = 1000).
OWNER="${BACKUP_UID:-1000}:${BACKUP_GID:-1000}"
DEST=/backups
MEDIA=/media

encrypt() {
    openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE
}

run_backup() {
    stamp=$(date +%Y-%m-%d_%H%M)
    db_part="$DEST/.db_$stamp.partial"
    media_part="$DEST/.media_$stamp.partial"
    echo "[backup] start $stamp"
    # Nedokončená záloha se při chybě smaže.
    trap 'rm -f "$db_part" "$media_part"' EXIT
    pg_dump -h "$DB_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc | encrypt > "$db_part"
    tar -C "$MEDIA" -cf - . | encrypt > "$media_part"
    mv "$db_part" "$DEST/db_$stamp.dump.enc"
    mv "$media_part" "$DEST/media_$stamp.tar.enc"
    trap - EXIT
    # I složka – když ji vytvořil Docker, patří rootovi a zálohy by nešly smazat.
    chown "$OWNER" "$DEST" "$DEST/db_$stamp.dump.enc" "$DEST/media_$stamp.tar.enc"
    find "$DEST" \( -name 'db_*.dump.enc' -o -name 'media_*.tar.enc' \) -mtime +"$RETENTION" -delete
    echo "[backup] hotovo db_$stamp.dump.enc ($(du -h "$DEST/db_$stamp.dump.enc" | cut -f1))," \
        "media_$stamp.tar.enc ($(du -h "$DEST/media_$stamp.tar.enc" | cut -f1))"
}

if [ "${1:-}" = "now" ]; then
    run_backup
    exit 0
fi

# Volume příloh založené dřívější verzí s vlastníkem root vrátí aplikaci (UID 1000).
if [ "$(stat -c %u "$MEDIA")" = "0" ]; then
    chown 1000:1000 "$MEDIA"
fi

echo "[backup] čekám na $BACKUP_TIME, uchovávám $RETENTION dní"
last=""
while true; do
    today=$(date +%Y-%m-%d)
    if [ "$(date +%H:%M)" = "$BACKUP_TIME" ] && [ "$last" != "$today" ]; then
        (run_backup) || echo "[backup] SELHALO" >&2
        last="$today"
    fi
    sleep 30
done
