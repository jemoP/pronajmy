# Zálohy Pronájmů (P15, ZM-010): pg_dump + tar příloh, šifrované AES-256.
FROM postgres:16-alpine
RUN apk add --no-cache openssl \
    # Přílohy sdílí volume se službou web (uživatel app, UID 1000) – i kdyby volume
    # založil tento kontejner, musí patřit aplikaci.
    && mkdir -p /media && chown 1000:1000 /media
COPY docker/backup.sh /backup.sh
COPY docker/restore.sh /restore.sh
ENTRYPOINT ["/bin/sh", "/backup.sh"]
