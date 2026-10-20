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

## Provoz (P15, P16, ZM-010)

Jeden `compose.yml` (projekt `pronajmy-prod`) pro autora i dalšího uživatele; návod pro dalšího
uživatele je [INSTALL.md](INSTALL.md), instalační balíček vytvoří `scripts/make-bundle.sh <verze>`
(`dist/pronajmy-install-<verze>.zip`: INSTALL.md, compose.yml, compose.demo.yml).

| Služba | Co dělá |
| --- | --- |
| `db` | PostgreSQL 16, volume `db_data` |
| `web` | `ghcr.io/jemop/pronajmy:${PRONAJMY_VERSION}`, přílohy ve volume `media_data`, port `${PRONAJMY_BIND}:${PRONAJMY_PORT}` |
| `backup` | `ghcr.io/jemop/pronajmy-backup`: denně v `BACKUP_TIME` šifrovaná záloha DB a příloh do `backups/` |
| `tailscale` | jen s profilem `tailscale`: `https://pronajmy.<tailnet>.ts.net`, uživatelský režim, `tailscale serve` |

### Provoz autora v LXC (Tailscale)

V LXC je `.env` vývojový, proto provoz používá `.env.prod` a všechny příkazy
`docker compose --env-file .env.prod -f compose.yml …`.

1. `docker run --rm ghcr.io/jemop/pronajmy:<verze> init-env --url https://pronajmy.<tailnet>.ts.net > .env.prod`
   a v něm upravit: `PRONAJMY_ENV_FILE=.env.prod`, `PRONAJMY_BIND=127.0.0.1` a `PRONAJMY_PORT=8010`
   (port jen uvnitř LXC – init-env by pro https:// nastavil 443), `DJANGO_HTTPS=true` (init-env pro https:// nastaví sám), doplnit `TS_AUTHKEY=` (auth key
   z administrace Tailscale, jednorázový) a `TS_HOSTNAME=pronajmy`. **`BACKUP_PASSPHRASE` uložit
   i mimo server.**
2. `docker login ghcr.io` (token `read:packages`), `mkdir backups`
3. `docker compose --env-file .env.prod -f compose.yml --profile tailscale up -d`
4. V administraci Tailscale u zařízení `pronajmy` vypnout **Disable key expiry**.

Bez GHCR (build z místního kódu): navíc `-f compose.prod-local.yml … up -d --build`.

### Aktualizace

```sh
docker compose --env-file .env.prod -f compose.yml exec backup /bin/sh /backup.sh now
# v .env.prod změnit PRONAJMY_VERSION
docker compose --env-file .env.prod -f compose.yml --profile tailscale pull
docker compose --env-file .env.prod -f compose.yml --profile tailscale up -d   # migrace při startu
```

### Zálohy a obnova

```sh
P="docker compose --env-file .env.prod -f compose.yml"
$P exec backup /bin/sh /backup.sh now                                       # ruční záloha DB + příloh
$P exec backup /bin/sh /restore.sh check /backups/db_<čas>.dump.enc          # obnova do dočasné DB, počty
$P exec backup /bin/sh /restore.sh media-check /backups/media_<čas>.tar.enc  # soubory vs. přílohy v DB
$P stop web                                                                  # obnova provozu:
$P exec backup /bin/sh /restore.sh restore /backups/db_<čas>.dump.enc
$P exec backup /bin/sh /restore.sh media-restore /backups/media_<čas>.tar.enc
$P start web
scripts/dev-from-prod.sh            # vývojová DB a media/ z poslední provozní zálohy
```

Zálohy leží na stejném disku jako data – zahrň LXC do záloh Proxmoxu nebo `backups/` kopíruj
jinam (NAS).

### Přístup dalšího uživatele k image (GitHub)

Image jsou privátní balíčky `pronajmy` a `pronajmy-backup` (vzniknou prvním během workflow).
U každého v GitHubu: Package settings → **Manage Actions access**: repozitář `pronajmy` s rolí
Write (aby workflow mohl dál nahrávat) → vypnout **Inherit access from source repository** →
**Manage access** → Invite: uživatel s rolí **Read**. Repozitář ani kód tím neuvidí.

### Vydání verze

1. Testy zelené, `main` odeslaný, tag `vX.Y.Z` → push tagu → GitHub Actions (testy, kontrola
   obsahu image, build amd64 + arm64, nahrání do GHCR).
2. `scripts/make-bundle.sh X.Y.Z` a zip poslat dalšímu uživateli (stačí při první instalaci
   nebo změně compose souborů; jinak jen číslo nové verze).
