#!/bin/sh
# Instalační balíček pro dalšího uživatele (ZM-010): INSTALL.md, CHANGELOG.md, compose.yml, compose.demo.yml
# s výchozí verzí image. Použití: scripts/make-bundle.sh <verze>  →  dist/pronajmy-install-<verze>.zip
set -eu
cd "$(dirname "$0")/.."
version="${1:?Použití: scripts/make-bundle.sh <verze, např. 1.0.0>}"
case "$version" in
  [0-9]*.[0-9]*.[0-9]*) ;;
  *) echo "Verze musí mít tvar X.Y.Z (bez v)." >&2; exit 2 ;;
esac

name="pronajmy-install-$version"
out="dist/$name"
rm -rf "$out" "dist/$name.zip"
mkdir -p "$out"
sed "s/@VERZE@/$version/g" INSTALL.md > "$out/INSTALL.md"
cp compose.yml "$out/compose.yml"
cp CHANGELOG.md "$out/CHANGELOG.md"
sed "s/PRONAJMY_VERSION:-latest/PRONAJMY_VERSION:-$version/g" compose.demo.yml > "$out/compose.demo.yml"
(cd dist && python3 -m zipfile -c "$name.zip" "$name")
rm -rf "$out"
echo "Balíček: dist/$name.zip"
