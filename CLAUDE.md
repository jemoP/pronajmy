# Pronájmy

Webová aplikace pro evidenci pronajímaných bytů (byty, nájemníci, smlouvy, platby, jistoty, komunikace, opravy, revize, výkaz). Zadání: docs/ZADANI-PRONAJMY.md (zdroj pravdy), historie změn zadání: docs/ZMENY.md, nápady: docs/NAPADY.md.

## Prostředí
- Vývoj běží v LXC 192.168.88.154 (Debian, Docker). Kód: /home/dev/pronajmy.
- Vývoj: compose projekt pronajmy, kontejnery web a db (compose.dev.yml), http://192.168.88.154:8002 (port 8000 drží Pokuty, 8001 HomeFinance).
- Provoz: compose.yml (projekt pronajmy-prod), přístup jen přes Tailscale (https://pronajmy.<tailnet>.ts.net).
- Python, uv a tailwindcss jsou JEN v kontejneru web – vše spouštěj přes docker compose exec.

## Stack
Python 3.12, uv, Django 5.2, PostgreSQL 16, Django šablony + HTMX + Tailwind CSS, Chart.js, pytest + pytest-django, ruff, mypy (django-stubs).

## Příkazy
- docker compose -f compose.dev.yml up -d --build                        # start / rebuild
- docker compose -f compose.dev.yml logs -f web                          # logy
- docker compose -f compose.dev.yml exec web uv run pytest
- docker compose -f compose.dev.yml exec web uv run ruff check --fix .
- docker compose -f compose.dev.yml exec web uv run ruff format .
- docker compose -f compose.dev.yml exec web uv run mypy apps config
- docker compose -f compose.dev.yml exec web uv run python manage.py migrate
- docker compose -f compose.dev.yml exec web uv run python manage.py makemigrations
- docker compose -f compose.dev.yml exec web uv run python manage.py createsuperuser
- Nová závislost: exec web uv add <balík>, pak rebuild.
- docker build --target prod --build-arg APP_VERSION=<verze> -t pronajmy:local .   # provozní image (jen .pyc)
- scripts/check-image.sh pronajmy:local                                    # obsah image vč. vrstev (žádné .py, data, .env)
- Zveřejnění image do GHCR: tag vX.Y.Z + push (GitHub Actions, amd64 + arm64) – jen na pokyn.

## Provoz (compose.yml, projekt pronajmy-prod)
- Postup a obnova ze zálohy: README.md. Tajné údaje v .env.prod (není v gitu).
- docker compose -f compose.yml up -d --build web                        # nasazení nové verze
- docker compose -f compose.yml exec backup /bin/sh /backup.sh now       # ruční záloha (DB + přílohy)
- docker compose -f compose.yml exec backup /bin/sh /restore.sh check /backups/<soubor>
- docker compose -f compose.yml exec backup /bin/sh /restore.sh media-check /backups/media_<čas>.tar.enc
- Provozní databázi, přílohy a zálohy měň jen na výslovný pokyn; testovací a kontrolní zásahy dělej ve vývoji. Nasazení jen na pokyn.

## Pravidla
- UI, hlášky a komentáře česky; identifikátory v kódu anglicky.
- Částky jen jako int v haléřích (*_cents), nikdy float ani Decimal pro částky.
- Změna schématu = vždy nová migrace přes makemigrations; datové migrace pro výchozí číselníky.
- Data jsou naprosto oddělená od HomeFinance: žádná společná databáze, import, export ani API mezi aplikacemi. Peníze pronájmů se zapisují jen sem.
- /home/dev/homefinance je jen zdroj kódu ke čtení (společný základ, archiv etapy 8: git show etapa-8-archiv:<soubor>); nic v něm neměň, necommituj a nespouštěj jeho kontejnery.
- Neměnit nic mimo /home/dev/pronajmy a nesahat na jiné Docker kontejnery v LXC (HomeFinance, Pokuty).
- Složky media/ a backups/, soubory .env* a výpisy databáze se nikdy necommitují ani nečtou do logů.
- Osobní údaje nájemníků jen v nezbytném rozsahu (bez rodného čísla a čísla dokladu); kontakty nikdy v exportech ani logách. Čísla účtů v UI maskovat.
- Přílohy: typ podle obsahu souboru, náhodné jméno, stahování jen přihlášeným, žádná veřejná MEDIA_URL.
- Stavy (dluh, revize, upozornění) vždy ikona + text, nikdy jen barva.
- Žádná tajemství v kódu – vše přes .env (není v gitu), vzor .env.example.
- Časy ukládej v UTC, zobrazuj v Europe/Prague.
- Po každé změně spustit ruff, mypy a pytest v kontejneru.
- Etapy podle sekce „Etapy a akceptace“ v docs/ZADANI-PRONAJMY.md, vždy nejdřív plán.

## Změny zadání
- Nápady, které se zatím nerealizují, zapisuj do docs/NAPADY.md (stav nápad / pozastaveno / odloženo / převedeno / zamítnuto); do ZMENY.md až po rozhodnutí je udělat.
- Při změně zadání nejdřív zapiš záznam do docs/ZMENY.md (stav „navrženo“) a uprav dotčené kapitoly ZADANI-PRONAJMY.md; implementuj až po schválení.
- Větší změny implementuj v samostatné git větvi.
- Po dokončení přepni stav záznamu na „hotovo“ a doplň datum a commit.

## Doména
- Druhy pohybů: INCOME příjem, EXPENSE náklad, TRANSFER převod mezi účty pronájmů, WITHDRAWAL výběr do domácnosti, DEPOSIT vklad z domácnosti.
- Výsledek: příjmy = INCOME s účelem druhu INCOME − EXPENSE s účelem druhu INCOME (vrácení příjmu, např. přeplatku); náklady = EXPENSE s účelem druhu EXPENSE. Jistota (neutrální účel), převody, výběry a vklady se nepočítají.
- Příjem a náklad mají byt (kromě ostatních příjmů / nákladů); platby, opravy a revize na pohyby jen odkazují.
- Předpisy: měsíčně z podmínek k 1. dni měsíce (smlouva + dodatky), neúplný měsíc poměrem dní na celé Kč, ruční předpis se nepřepisuje.
- Saldo = předpisy − platby, FIFO od nejstarší splatnosti; jistota se sleduje mimo saldo.
