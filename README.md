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

## Provoz

Provoz přes Tailscale a šifrované zálohy databáze i příloh přibudou v etapě 5.
