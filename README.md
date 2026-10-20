# Pronájmy

Evidence pronajímaných bytů – byty, nájemníci, smlouvy, platby, jistoty, komunikace, opravy,
revize a výkaz. Zadání: [docs/ZADANI-PRONAJMY.md](docs/ZADANI-PRONAJMY.md).

## Vývoj

Vývoj běží v LXC 192.168.88.154 v compose projektu `pronajmy` (`compose.dev.yml`: `web`, `db`),
aplikace je na http://192.168.88.154:8002. Python, uv a Tailwind jsou jen v kontejneru `web`.

```sh
cp .env.example .env            # vyplnit DJANGO_SECRET_KEY a heslo databáze
docker compose -f compose.dev.yml up -d --build
docker compose -f compose.dev.yml exec web uv run python manage.py migrate
docker compose -f compose.dev.yml exec web uv run python manage.py createsuperuser
```

Kontroly (po každé změně):

```sh
docker compose -f compose.dev.yml exec web uv run ruff check --fix .
docker compose -f compose.dev.yml exec web uv run ruff format .
docker compose -f compose.dev.yml exec web uv run mypy apps config
docker compose -f compose.dev.yml exec web uv run pytest
```

Bez přihlášení je dostupná jen přihlašovací stránka a `/health`.

## Provozní image (ZM-010)

Jeden `Dockerfile`: `target: dev` pro vývoj, `target: prod` pro provoz a distribuci. Provozní image
obsahuje jen zkompilovaný Python (`.pyc`), sebrané statické soubory a šablony; testy, dokumentace
a zdrojové `.py` v něm nejsou ani v nižších vrstvách.

```sh
docker build --target prod --build-arg APP_VERSION=0.5.0 -t pronajmy:local .
scripts/check-image.sh pronajmy:local       # obsah image a všech vrstev
docker run --rm pronajmy:local init-env --url http://192.168.1.50:8080 > .env
```

Vstupní skript image: `web` (výchozí – čeká na databázi, `migrate`, při prvním startu založí účet
z `PRONAJMY_ADMIN_USER` / `PRONAJMY_ADMIN_PASSWORD`, gunicorn), `init-env --url …` (vypíše `.env`
s novými tajnými hodnotami), `manage <příkaz>`.

Nastavení navíc: `PRONAJMY_URL` (doplní povoleného hostitele a CSRF), `DJANGO_HTTPS=false`
(provoz v lokální síti po HTTP), `DATABASE_URL` je volitelná – jinak se skládá z `POSTGRES_*`.

Zveřejnění: tag `vX.Y.Z` a push → GitHub Actions spustí testy, zkontroluje obsah image a nahraje
`ghcr.io/jemop/pronajmy:X.Y.Z` a `latest` pro `linux/amd64` a `linux/arm64` (Raspberry Pi
s 64bitovým systémem). Balíček je privátní; přístup ke čtení se přidává v nastavení balíčku
na GitHubu (Package settings → Manage access).

## Demo (ZM-010)

Demo se smyšlenými daty je samostatný compose projekt `pronajmy-demo` (`compose.demo.yml`:
`db`, `web`, volitelně `reset`) s vlastní databází `pronajmy_demo` a přílohami; `.env` nepotřebuje.
Při prvním startu se prázdná databáze naplní příkazem `seed_demo` (3 roky historie relativně
k dnešku), přihlášení demo / demo, na každé stránce pruh „Demo – smyšlená data“, změna hesla
je vypnutá.

```sh
docker compose -f compose.demo.yml -f compose.local.yml up -d --build    # z místního kódu, :8003
docker compose -f compose.demo.yml up -d                                 # z GHCR (po zveřejnění)
docker compose -f compose.demo.yml exec web python manage.pyc seed_demo --reset   # obnova dat
docker compose -f compose.demo.yml --profile reset up -d                 # obnova každý den ve 03:00
docker compose -f compose.demo.yml down -v                               # konec dema i s daty
```

Pojistky: `seed_demo` běží jen při `DEMO_MODE=True` nad databází s „demo“ v názvu a aplikace
s `DEMO_MODE=True` nad jinou databází nenastartuje.

## Provoz

Provoz přes Tailscale a šifrované zálohy databáze i příloh přibudou v etapě 5.
