# Pronájmy – zadání a založení projektu

Verze: 17. 10. 2026, ZM-003 (historie změn: [ZMENY.md](ZMENY.md))

## Účel a rozsah

Pronájmy je webová aplikace pro evidenci pronajímaných bytů: byty, nájemníci, smlouvy a dodatky,
předpisy a platby nájmu, jistoty, komunikace s nájemníky, opravy, pravidelné revize a výsledek
pronájmů včetně podkladu pro daňové přiznání.

Pronájmy jsou samostatná účetní jednotka s vlastním bankovním účtem, a proto samostatná aplikace
s vlastní databází, přihlášením, provozem a zálohami. **Data jsou naprosto oddělená od domácích
financí (aplikace HomeFinance):** žádná společná databáze, import ani automatický přenos.
Peníze pronájmů se zapisují jen sem. Výběr zisku na domácí účet je zde „výběr do domácnosti“;
v domácích financích se zapisuje zvlášť, ručně, jako běžný příjem.

V rozsahu první verze:

- vlastní evidence peněz pronájmů: účty, účely, pohyby, zůstatky,
- byty a nájemníci, nájemní smlouvy a dodatky, ukončení smlouvy,
- měsíční předpisy nájmu a záloh, platby, saldo a dlužníci, jistota,
- komunikace s nájemníky s termínem vyřízení,
- opravy a pravidelné revize s upozorněním,
- přílohy (skeny smluv, protokoly, fotky),
- upozornění, výkaz po bytech, podklad pro daňové přiznání, export CSV / XLSX,
- provoz přes Tailscale, šifrované zálohy databáze i příloh.

Mimo rozsah první verze: import historických dat (dřívější smlouvy a pohyby se zadají ručně),
vyúčtování služeb (nedoplatek / přeplatek se zadá ručním předpisem), šablony smluv, odesílání
e-mailů a SMS, import bankovního výpisu a párování plateb, portál pro nájemníky, napojení na
jiné aplikace.

## Původ

Funkce jsou převzaté z etapy 8 aplikace HomeFinance (změna ZM-011), která byla dokončena
a ověřena, ale do HomeFinance se nesloučila (ZM-012). Její kód je v LXC v repozitáři
`/home/dev/homefinance` pod tagem `etapa-8-archiv` (`git show etapa-8-archiv:<soubor>`):
`apps/rentals/` (modely, služby, formuláře, pohledy, testy) a `templates/rentals/`.
Z HomeFinance se dál přebírá společný základ: `apps/core` (formátování, export, přihlášení),
`templates/base.html`, `templates/registration/`, `assets/css/input.css`, `static/vendor/`
(htmx, Chart.js), `static/js/charts.js`, Dockerfile, compose soubory, `docker/` (zálohy).
Kód se jednorázově zkopíruje a přizpůsobí; za běhu ani jako balíček se nic nesdílí.

Hlavní rozdíl proti etapě 8: místo pohybů HomeFinance (`ledger.Transaction`, oblasti
Domácnost / Pronájmy, byt u pohybu) má aplikace vlastní pohyby `entry` (viz Datový model).

## Datový model

Částky jsou vždy celá čísla v haléřích (`*_cents`), nikdy float ani Decimal. Časy v UTC,
zobrazení v Europe/Prague. Názvy tabulek odpovídají tabulce níže (`Meta.db_table`).

### Peníze (aplikace `money`)

| Tabulka | Klíčové sloupce | Poznámka |
| --- | --- | --- |
| `account` | id, name, kind (BANK / CASH), bank_code, account_number, opening_balance_cents, active | Účet pronájmů; zůstatek = počáteční stav + příchozí − odchozí pohyby |
| `category` | id, name, kind (INCOME / EXPENSE / NEUTRAL), code, sort, active | Účel pohybu; `code` = interní označení výchozího účelu (unikátní, u účelů přidaných uživatelem prázdné) |
| `entry` | id, date, kind (INCOME / EXPENSE / TRANSFER / WITHDRAWAL / DEPOSIT), amount_cents (> 0), account_id, to_account_id, category_id, property_id, note, created_at, updated_at | Pohyb peněz |

Výchozí účely (datová migrace): příjmy Nájemné, Zálohy na služby, Vyúčtování služeb, Ostatní
příjmy; náklady Opravy a údržba, Revize, Pojištění, Daň z nemovitosti, Fond oprav / SVJ, Služby,
Správa a inzerce, Poplatky, Ostatní náklady; neutrální Jistota.

Výchozí účely mají interní `code` (RENT, SERVICES, SETTLEMENT, OTHER_INCOME, REPAIRS,
INSPECTION, INSURANCE, PROPERTY_TAX, HOA_FUND, UTILITIES, MANAGEMENT, FEES, OTHER_EXPENSE,
DEPOSIT), podle kterého je aplikace najde i po přejmenování. Účel s kódem jde přejmenovat,
přeřadit a deaktivovat, ale ne smazat ani změnit jeho druh.

Pravidla pohybů:

- INCOME a EXPENSE mají povinný účel odpovídajícího druhu (NEUTRAL jde u obou – jistota přijatá
  je příjem, vrácená výdaj; EXPENSE smí mít i účel druhu INCOME = vrácení příjmu, např. vrácený
  přeplatek) a povinný byt (`property_id`), kromě účelu „Ostatní příjmy /
  náklady“, kde je byt volitelný.
- TRANSFER = převod mezi dvěma účty pronájmů (`to_account_id` povinný a jiný než `account_id`).
- WITHDRAWAL = výběr do domácnosti (odchází z účtu), DEPOSIT = vklad z domácnosti (přichází).
  TRANSFER, WITHDRAWAL a DEPOSIT nemají účel ani byt.
- Výsledek: příjmy = INCOME s účelem druhu INCOME − EXPENSE s účelem druhu INCOME (vrácení
  příjmu snižuje příjmy, ne zvyšuje náklady); náklady = EXPENSE s účelem druhu EXPENSE;
  zisk = příjmy − náklady. Neutrální účely (jistota), převody, výběry a vklady se nepočítají.
- Pohyb s datem v budoucnosti je plánovaný: nepočítá se do aktuálního zůstatku ani výsledku.

### Pronájmy (aplikace `rentals`)

| Tabulka | Klíčové sloupce | Poznámka |
| --- | --- | --- |
| `property` | id, name (unikátní), address, unit, layout, floor_area (m², nejde o částku), account_id, active, note | Byt; účet = výchozí pro zápis platby |
| `tenant` | id, name, phone, email, address, birth_date, active, note | Rodné číslo ani číslo dokladu se neukládají |
| `lease` | id, property_id, number, signed_date, start_date, end_date (NULL = doba neurčitá), rent_cents, services_cents, due_day (1–31), deposit_cents, variable_symbol, account_id, status (DRAFT / ACTIVE / ENDED), charges_from, terminated_on, termination_reason, note | Smlouva |
| `lease_tenant` | lease_id, tenant_id, role (MAIN / CO_TENANT) | Nájemce a spolunájemci; dvojice unikátní |
| `lease_amendment` | id, lease_id, number, signed_date, effective_date, description, rent_cents, services_cents, end_date (NULL = beze změny) | Dodatek |
| `rent_charge` | id, lease_id, kind (RENT / SERVICES / SETTLEMENT / DEPOSIT / OTHER), period (1. den měsíce), due_date, amount_cents (se znaménkem), manual, note | Předpis; RENT a SERVICES nejvýš jednou na smlouvu a měsíc a vždy s `period` |
| `rent_payment` | id, lease_id, entry_id (NULL jen u započtení), kind (PAYMENT / DEPOSIT / REFUND / DEPOSIT_RETURN / DEPOSIT_OFFSET), amount_cents (> 0), date (jen u započtení), note | Vazba pohybu na smlouvu; smazání pohybu vazbu odstraní |
| `communication` | id, property_id, lease_id, tenant_id (aspoň jedno), occurred_at, channel (PHONE / EMAIL / SMS / IN_PERSON / LETTER / OTHER), direction (IN / OUT), subject, text, follow_up_date, follow_up_done | Deník komunikace |
| `repair` | id, property_id, lease_id, reported_date, reported_by, title, description, status (REPORTED / ORDERED / DONE / CANCELLED), contractor, done_date, cost_cents, paid_by (OWNER / TENANT / INSURANCE), entry_id | Oprava / závada |
| `inspection_type` | id, name, interval_months, remind_days (výchozí 30), active, note | Druh revize |
| `inspection_plan` | id, property_id, type_id, device, interval_months (NULL = podle druhu), first_due_date, active, note | Co a jak často se v bytě kontroluje |
| `inspection` | id, plan_id, done_date, next_due_date, result (OK / DEFECTS / FAILED), contractor, cost_cents, entry_id, note | Provedená revize |
| `attachment` | id, lease_id / amendment_id / communication_id / repair_id / inspection_id (právě jedno), file, original_name, content_type, size, uploaded_at | Příloha |

Výchozí druhy revizí (datová migrace; jen návrh, lhůty je potřeba ověřit podle zařízení
a předpisů): kontrola a čištění spalinové cesty 12 měsíců, servis plynového kotle 12, revize
plynového zařízení 36, revize elektroinstalace 60, kontrola hasicího přístroje 12, výměna /
ověření vodoměrů 60.

### Pravidla pronájmů

- **Podmínky k datu** = smlouva + dodatky účinné nejpozději ten den (nájem, zálohy, konec).
  Skutečný konec nájmu = ukončení, jinak sjednaný konec (i z dodatku).
- **Překrývání:** na jeden byt nejvýš jedna smlouva v daném dni; návrhy (DRAFT) se nepočítají.
- **Předpisy** RENT a SERVICES se doplňují do aktuálního měsíce včetně (při otevření pronájmů,
  idempotentně) od měsíce `charges_from` (výchozí začátek nájmu) do konce nájmu, z podmínek
  platných k 1. dni měsíce (u prvního neúplného měsíce k začátku nájmu). Neúplný první
  a poslední měsíc se krátí poměrem dní, zaokrouhleno na celé Kč. Splatnost = `due_day`
  v měsíci (u kratšího měsíce poslední den). Automatický předpis se při změně podmínek
  přepočítá; ručně upravený (`manual`) zůstává, dokud se nevrátí na automatický.
- **Jistota:** předpis DEPOSIT vzniká, jen když se saldo sleduje od začátku nájmu.
  Sleduje se mimo saldo: přijato (DEPOSIT) − vráceno (DEPOSIT_RETURN, výdaj) − započteno
  (DEPOSIT_OFFSET bez pohybu, sníží dluh). Vrátit či započíst jde nejvýš drženou jistotu.
- **Saldo** = předpisy bez DEPOSIT − (platby PAYMENT + započtení − vrácené přeplatky REFUND).
  Počítají se jen platby od `charges_from`. Platby a záporné předpisy (přeplatek, sleva) kryjí
  kladné předpisy od nejstarší splatnosti (FIFO); po splatnosti je nekrytá část předpisu se
  splatností před dneškem.
- **Zápis platby** v aplikaci vytvoří příjmy na účet smlouvy rozdělené podle předpisů, které
  platba kryje (Nájemné, Zálohy na služby, Vyúčtování služeb; přeplatek jako Nájemné), a zvlášť
  příjem s účelem Jistota. Vrácení přeplatku je EXPENSE s účelem Vyúčtování služeb (sníží
  příjmy), vrácení jistoty EXPENSE s účelem Jistota. Existující příjem jde ke smlouvě přiřadit celý nebo po částech;
  aplikace navrhne nepřiřazené příjmy bytu nebo na účet smlouvy (45 dní před začátkem až
  45 dní po konci nájmu), nejbližší měsíční platbě nahoře.
- **Ukončení smlouvy** s nevyrovnaným saldem nebo drženou jistotou jen s výslovným potvrzením.
  Smazat jde jen návrh smlouvy.
- **Opravy a revize:** s náklady, zvoleným účtem a (u oprav) platí-li pronajímatel vznikne
  jednou výdaj s účelem Opravy a údržba / Revize a bytem. Příští termín revize = provedení +
  interval (jde ručně změnit); bez provedené revize platí první termín.
- **Upozornění:** nájem po splatnosti; konec smlouvy do 60 dní a smlouva po konci, která není
  ukončená; revize v okně `remind_days` a po termínu; otevřené opravy; komunikace k vyřízení
  do 3 dní a po termínu. Nejdřív položky po termínu; vždy ikona + text, nikdy jen barva.
- **Přílohy:** PDF, JPG, PNG do 20 MB; typ se určuje podle obsahu souboru, ne podle přípony;
  soubor se uloží pod náhodným jménem, stahuje se jen přes přihlášenou stránku (žádná veřejná
  adresa médií); smazání záznamu (i kaskádou) smaže soubor.

## Funkční požadavky

| ID | Oblast | Požadavek | Priorita |
| --- | --- | --- | --- |
| P01 | Peníze | Účty pronájmů, aktuální zůstatek a zůstatek k datu | Musí |
| P02 | Peníze | Pohyby: zadání, úprava, smazání; seznam s filtrem (období, druh, účel, byt, účet, text), součty, stránkování | Musí |
| P03 | Peníze | Číselník účelů (druh, pořadí, aktivní) | Musí |
| P04 | Byty | Byty a nájemníci; karta bytu s aktuální smlouvou, saldem, opravami, revizemi a komunikací | Musí |
| P05 | Smlouvy | Smlouvy s více nájemníky, doba určitá / neurčitá, dodatky, historie podmínek, ukončení, historické smlouvy se „sledovat saldo od“ | Musí |
| P06 | Platby | Předpisy, zápis platby, přiřazení pohybu s návrhem, ruční předpisy, saldo, dlužníci | Musí |
| P07 | Platby | Jistota: přijetí, vrácení, započtení na dluh | Musí |
| P08 | Komunikace | Deník kontaktů s termínem vyřízení a přílohami | Má |
| P09 | Opravy | Stav, dodavatel, náklady, kdo platí, výdaj, přílohy | Musí |
| P10 | Revize | Plán po bytech a zařízeních, historie s protokoly, příští termín, číselník druhů | Musí |
| P11 | Přehledy | Upozornění na všech stránkách a v přehledu pronájmů | Má |
| P12 | Přehledy | Výkaz po bytech a měsících / letech (příjmy, náklady podle účelů, zisk, meziročně, graf), zůstatky účtů, výběry a vklady | Musí |
| P13 | Přehledy | Podklad pro daňové přiznání (§ 9): příjmy, skutečné výdaje proti paušálu 30 %, nejvýš 600 000 Kč ročně; upozornění, že skutečné výdaje nezahrnují odpisy ani úroky | Má |
| P14 | Export | Export pohybů a výkazu do CSV (český Excel: UTF-8 s BOM, středník, desetinná čárka) a XLSX; bez kontaktů nájemníků a čísel účtů | Má |
| P15 | Zálohy | Denní šifrovaná záloha databáze a příloh, kontrola a obnova | Musí |
| P16 | Přístup | Přihlášení heslem (jeden účet), provoz jen přes Tailscale | Musí |

Nefunkční požadavky: UI v češtině, částky „1 234,50 Kč“, data „15. 10. 2026“; responzivní na
mobilu; vše lokálně, žádné cloudové služby a CDN; osobní údaje nájemníků jen v nezbytném
rozsahu, kontakty se neexportují ani nezapisují do logů; čísla účtů v UI maskovaná.

## Technologie a architektura

Stejný stack jako HomeFinance a Pokuty: Python 3.12, uv (`uv.lock`), Django 5.2 (LTS),
PostgreSQL 16, Django šablony + HTMX + Tailwind CSS (samostatný CLI binár, bez Node.js),
Chart.js, pytest + pytest-django, ruff (ruff format), mypy (strict, django-stubs).

| Vrstva | Volba |
| --- | --- |
| Vývoj | LXC 192.168.88.154, Docker; compose projekt `pronajmy` (`compose.dev.yml`: `web`, `db`), http://192.168.88.154:8002 (8000 Pokuty, 8001 HomeFinance) |
| Provoz | `compose.yml`, projekt `pronajmy-prod` ve stejném LXC: `db`, `web` (gunicorn, WhiteNoise), `backup`, `tailscale` (`https://pronajmy.<tailnet>.ts.net`, uživatelský režim, `tailscale serve`); žádný port z LXC ven |
| Přílohy | vývoj `media/` v projektu (v .gitignore a .dockerignore), provoz volume `media_data` |
| Zálohy | služba `backup`: denně `pg_dump` + tar příloh, AES-256 (`BACKUP_PASSPHRASE`), 30 dní; `restore.sh check / restore / dump / media-check / media-restore / media-dump` |
| Tajné údaje | `.env` / `.env.prod` (mimo git), vzory `.env.example` / `.env.prod.example` |

Struktura repozitáře:

```
pronajmy/                  # v LXC: /home/dev/pronajmy
├── CLAUDE.md
├── docs/ZADANI-PRONAJMY.md, docs/ZMENY.md, docs/NAPADY.md
├── Dockerfile, compose.dev.yml, compose.yml, README.md
├── docker/                # backup.sh, restore.sh, backup.Dockerfile, tailscale/serve.json
├── scripts/               # dev-from-prod.sh
├── manage.py, pyproject.toml, uv.lock
├── config/                # nastavení Django, urls
├── apps/
│   ├── core/              # formátování, export, přihlášení, společné šablonové tagy
│   ├── money/             # účty, účely, pohyby
│   └── rentals/           # byty, nájemníci, smlouvy, platby, údržba, přílohy, výkaz
├── templates/, assets/css/input.css, static/
├── media/                 # přílohy ve vývoji – v .gitignore
└── backups/               # šifrované zálohy – v .gitignore
```

## Etapy a akceptace

Každá etapa: plán → schválení → samostatná větev → zelené testy (ruff, mypy, pytest
v kontejneru) → commit → kontrola uživatelem → merge.

| Etapa | Obsah | Hotovo, když |
| --- | --- | --- |
| 0 Kostra | Repo, uv, Dockerfile, compose.dev.yml (port 8002), Django + přihlášení, Tailwind, převzaté `core`, CLAUDE.md, docs | Testy v kontejneru projdou, aplikace běží na :8002, bez přihlášení není přístupná žádná stránka kromě přihlášení a /health |
| 1 Peníze | P01–P03, export pohybů; byty (`property`) jen seznam a formulář (ZM-002) | Příjem zvýší a výdaj sníží zůstatek účtu; výběr do domácnosti sníží zůstatek, ale nezmění výsledek; převod mezi účty nezmění součet zůstatků |
| 2 Smlouvy a platby | P04–P07 (převod kódu etapy 8 na `entry`) | Smlouva od 1. 1. 2026 (nájem 15 000 Kč + zálohy 3 000 Kč, splatnost 5. dne) s dodatkem od 1. 7. 2026 (nájem 16 000 Kč) a platbami 18 000 Kč za leden–září ukáže k 16. 10. 2026 dluh 22 000 Kč po splatnosti; platby se rozdělí na nájemné 138 000 Kč a zálohy 24 000 Kč |
| 3 Údržba a přílohy | P08–P10, přílohy | Revize kotle provedená 1. 11. 2025 s intervalem 12 měsíců je k 16. 10. 2026 v upozorněních „za 16 dní“; oprava zaplacená z účtu sníží výsledek bytu; příloha s neplatným obsahem se odmítne |
| 4 Přehledy | P11–P14 | Výkaz sedí s pohyby (jistota a výběry se nepočítají); paušál respektuje strop; export neobsahuje kontakty |
| 5 Provoz | P15, P16: compose.yml, Tailscale, zálohy, README | Aplikace je dostupná přes Tailscale; záloha a obnova databáze i příloh ověřena |

## Založení projektu

1. V LXC jako `dev`: `mkdir /home/dev/pronajmy && cd /home/dev/pronajmy && git init`;
   nakopírovat `CLAUDE.md` a `docs/ZADANI-PRONAJMY.md`; `.gitignore` s řádky `.env`,
   `.env.prod`, `.venv/`, `__pycache__/`, `media/`, `backups/`, `staticfiles/`,
   `static/css/app.css`.
2. Na GitHubu založit privátní repozitář `jemoP/pronajmy`, `git remote add origin
   git@github.com:jemoP/pronajmy.git`.
3. Ve VS Code (Remote-SSH) otevřít `/home/dev/pronajmy` a do workspace přidat složku – Claude
   Code pak smí číst `/home/dev/homefinance` jako zdroj kódu.
4. Prompt pro etapu 0:

```text
Přečti docs/ZADANI-PRONAJMY.md a CLAUDE.md. Proveď etapu 0: kostru projektu podle zadání,
společný základ převezmi z /home/dev/homefinance (jen čti, nic tam neměň). Nejdřív mi ukaž
plán. Na konci spusť v kontejneru ruff, mypy a pytest a vše oprav, dokud neprojde.
```
