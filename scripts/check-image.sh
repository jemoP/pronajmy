#!/bin/sh
# Kontrola obsahu provozního image (ZM-010): žádné zdrojové .py aplikace, testy, dokumentace,
# přílohy (media/ jen prázdná), zálohy ani .env. Použití: scripts/check-image.sh <image>
set -eu
image="${1:?Použití: scripts/check-image.sh <image>}"

docker run --rm --entrypoint sh "$image" -c '
  cd /app
  found=$(
    find . -name "*.py"
    find ./media -mindepth 1 2>/dev/null
    find . \( -name tests -o -name docs -o -name backups -o -name ".env*" \
           -o -name "*.dump*" -o -name "*.sql" -o -name CLAUDE.md -o -name .git \) -print
  )
  if [ -n "$found" ]; then
    echo "Image obsahuje nepovolené soubory:" >&2
    echo "$found" >&2
    exit 1
  fi
  test -f manage.pyc && test -f config/settings.pyc && test -f staticfiles/staticfiles.json
'
# Smazané soubory by zůstaly v nižších vrstvách – projdou se všechny vrstvy exportu image.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
docker save "$image" -o "$tmp/image.tar"
tar -xf "$tmp/image.tar" -C "$tmp"
if [ ! -d "$tmp/blobs" ]; then
  echo "Neznámý formát exportu image (chybí blobs/)." >&2
  exit 1
fi
leaks=$(find "$tmp/blobs" -type f ! -name '*.json' | while read -r blob; do
  tar -tf "$blob" 2>/dev/null | grep -E '^app/.*\.py$|^app/(tests|docs|backups)/|^app/media/.|^app/\.env' || true
done)
if [ -n "$leaks" ]; then
  echo "Vrstvy image obsahují nepovolené soubory:" >&2
  echo "$leaks" | sort -u >&2
  exit 1
fi
echo "Obsah image $image v pořádku."
