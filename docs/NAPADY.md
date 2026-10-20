# Nápady na rozšíření

Nápady, které zatím nejsou schválené k realizaci. Když se nápad rozhodne udělat, dostane záznam
v [ZMENY.md](ZMENY.md) (stav „navrženo“) a tady se u něj doplní odkaz. Nejnovější nahoře.

**Stavy:** `nápad` – jen zapsáno · `pozastaveno` – rozpracovaná úvaha, čeká · `odloženo` – vědomě
na později · `převedeno` – realizuje se přes ZM-xxx · `zamítnuto` – nebude se dělat

---

## Zjednodušení distribuce a aktualizací
- **Stav:** nápad (2026-10-20, navazuje na ZM-010; předpoklad: Docker a Compose u uživatele jsou)
- **Popis:** zkušenost z první instalace (1.0.0 na Raspberry Pi) – drhne účet a token na GitHubu,
  přenos zipu, ručně opsaná adresa (Bad Request 400, řešeno v 1.0.1), ruční úprava `.env`
  a záloha před aktualizací, demo a provoz ve dvou složkách. Možnosti:
  1. **Instalátor v image:** `docker run --rm --network host -v "$PWD:/install"
     ghcr.io/jemop/pronajmy:1 install` zapíše `compose.yml`, `.env` (adresa, UID, hesla),
     `INSTALL.md` a `backups/` a vypíše další krok – odpadne zip i `init-env` a `mkdir`.
  2. **Kanál hlavní verze:** tag image `1` vedle `1.0.1`, `compose.yml` s `:1` – aktualizace
     = `docker compose pull && docker compose up -d` bez úpravy `.env`; verze 2 se nestáhne omylem.
  3. **Automatická záloha před aktualizací:** `backup` při startu pozná novou verzi
     (`PRONAJMY_VERSION` / verze image), zazálohuje a teprve pak pustí `web` k migracím
     (`depends_on` na zdravou zálohu).
  4. **Demo a provoz v jednom `compose.yml`** (demo jako profil) – jeden soubor; demo dál
     ve vlastním projektu kvůli oddělení dat.
  5. **Přístup bez účtu na GitHubu:** sdílený token robotického účtu jen pro čtení balíčků;
     nevýhoda: sdílený přístupový údaj, při úniku zneplatnit a poslat všem nový.
  6. **Veřejné image:** odpadne `docker login`; v rozporu s požadavkem „uživatel nesmí vidět
     kód“ (`.pyc` jde dekompilovat) – nedoporučeno.
  7. **Offline přenos** (`docker save` / `docker load`): bez registru a účtu; každá verze jako
     soubor přes 100 MB – jen nouzově.
  8. **Automatické aktualizace** (Watchtower): jen spolu s 2 a 3.
- **Doporučení:** 1 + 2 + 3 (instalace = `docker login`, `install`, `up -d`; aktualizace =
  `pull` + `up -d` se zálohou automaticky); 5 podle počtu uživatelů.
- **Otevřené otázky:** které body realizovat; robotický účet ano / ne; má `install` umět
  i demo (`install --demo`)?

## Oddělený výsledek nájmu a služeb
- **Stav:** převedeno (2026-10-19, realizuje se jako [ZM-008](ZMENY.md))
- **Popis:** příjmy a náklady rozdělit na dvě oddělená porovnání; celkový zisk se nemění.
  - **Nájem:** Nájemné, Ostatní příjmy proti nákladům mimo služby (opravy, revize, pojištění,
    daň z nemovitosti, fond oprav / SVJ, správa, poplatky, ostatní) → zisk z nájmu.
  - **Služby:** Zálohy na služby + Vyúčtování služeb (nedoplatky − vrácené přeplatky) proti
    energiím a Službám → rozdíl služeb (kladný = zálohy pokryly náklady).
  - Rozlišení: příznak u účelu „Služba (průběžná položka)“ (výchozí: zálohy, vyúčtování, energie,
    Služby; jde zapnout i u vlastních účelů), nezávislý na příznaku „Do daní“; záložka Služby
    a energie (ZM-007) by se řídila jím místo pevných kódů.
  - Zobrazení: Výkaz › Výsledek a daně (dvě řady dlaždic, tabulka po bytech ve dvou blocích
    s mezisoučty, měsíce a roky se ziskem z nájmu a rozdílem služeb, graf jen nájmu, export),
    Přehled (dlaždice zisk z nájmu a rozdíl služeb), karta bytu. Pohyby a daně beze změny.
- **Otevřené otázky:** příznak u účelu, nebo pevně podle kódů (doporučeno: příznak); Fond oprav /
  SVJ v nájmu (zálohy přes SVJ rozepsat v Platbách na energie); rozsah Výkaz + Přehled + karta
  bytu, nebo jen Výkaz (doporučeno: vše).

## Demo aplikace se smyšlenými daty
- **Stav:** převedeno (2026-10-20, realizuje se jako [ZM-010](ZMENY.md) – demo pro jiného
  uživatele v jeho lokální síti, přihlášení demo/demo, noční obnova volitelná)
- **Popis:** samostatná demo instance ze stejného kódu, bez kopie skutečných dat (kopie +
  mazání by mohla vynést osobní údaje – přílohy, poznámky, sezení, admin log, výpisy DB).
  - `compose.demo.yml`, projekt `pronajmy-demo`: vlastní DB a volume příloh, `.env.demo` mimo git,
    provozní nastavení (gunicorn, DEBUG=False, WhiteNoise); obraz se staví jen na pokyn.
  - `DEMO_MODE=True`: pruh „Demo – smyšlená data“ na každé stránce, ukázkové přihlášení na
    přihlašovací stránce.
  - Příkaz `manage.py seed_demo [--reset]`: pojistky (jen při `DEMO_MODE` a nad DB s „demo“
    v názvu), `--reset` vymaže DB i přílohy. Deterministická data relativní k dnešku, 2–3 roky
    historie: 2 účty, 4 byty (vč. garáže bez nájmu), smyšlení nájemníci (@example.cz,
    600 000 xxx), smlouvy (s dodatkem, se spolunájemcem a dluhem 2 měsíce, ukončená s vrácenou
    a započtenou jistotou, návrh, končící do 60 dní), platby přes „Zaplaceno“ i FIFO, částečná
    platba, vrácený přeplatek, revize za 16 dní a po termínu, opravy, komunikace po termínu,
    ukázkové PDF/PNG přílohy, platby dodavatelům (SVJ s rozpisem, elektřina, roční pojištění,
    SIPO automaticky, nezaplacená splátka), výběry, vklad, převod.
  - Volitelně noční obnova (`seed_demo --reset` ve 03:00).
  - Testy: pojistky, platnost vygenerovaných dat, vykreslení stránek, neprázdný přehled a výkaz.
- **Otevřené otázky:** přístup (LAN port 8003 / uzel Tailscale `pronajmy-demo` / veřejně přes
  Funnel), přihlášení (veřejné demo/demo / vlastní heslo), noční obnova (ano / ne), pořadí
  vůči etapě 5 (po ní jednodušší – převezme provozní nastavení).

## Vyúčtování služeb
- **Stav:** odloženo (2026-10-16, vypuštěno z původního zadání v HomeFinance ZM-011)
- **Popis:** za zvolené období předvyplnit předepsané zálohy, zadat skutečné náklady, rozdíl
  vytvoří předpis nedoplatku / přeplatku; případně rozpis po službách (voda, teplo, elektřina
  společných prostor) a odečty měřidel. Do té doby se nedoplatek / přeplatek zadává ručním předpisem.

## Import bankovního výpisu a párování plateb
- **Stav:** nápad (2026-10-16)
- **Popis:** načíst výpis účtu pronájmů (CSV / GPC), založit pohyby a platby spárovat se
  smlouvami podle variabilního symbolu.

## Šablony smluv, dodatků a upomínek
- **Stav:** nápad (2026-10-16)
- **Popis:** generování PDF ze šablon; odesílání upomínek e-mailem (změna požadavku „vše lokálně“).

## Inflační doložka
- **Stav:** nápad (2026-10-16)
- **Popis:** návrh zvýšení nájmu podle indexu spotřebitelských cen; vytvoří návrh dodatku.

## Předávací protokoly u smlouvy
- **Stav:** nápad (2026-10-16, upřesněno 2026-10-17)
- **Popis:** evidence předávacích protokolů u nájemní smlouvy. Protokol vzniká při podpisu
  (předání bytu nájemníkovi) a při ukončení smlouvy (převzetí bytu zpět). Obsah:
  - datum předání a kdo byl přítomen,
  - stavy měřičů (voda studená / teplá, elektřina, plyn, teplo – měřidlo, číslo, stav),
  - popis stavu bytu (po místnostech nebo volným textem), zjištěné závady,
  - předané klíče a vybavení,
  - přílohy a fotografie (využít stávající přílohy – PDF, JPG, PNG).
- **Souvislosti:** porovnání stavů měřičů při převzetí s předáním jako podklad pro vyúčtování
  služeb (viz nápad Vyúčtování služeb); závady zjištěné při převzetí jako podklad pro započtení
  jistoty nebo založení opravy.

## Souhrn pro Home Assistant
- **Stav:** nápad (2026-10-16)
- **Popis:** endpoint s tokenem – dlužné nájmy, blížící se revize, otevřené opravy. Do HomeFinance
  se nic nepřenáší (data oddělená).
