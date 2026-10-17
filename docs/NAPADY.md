# Nápady na rozšíření

Nápady, které zatím nejsou schválené k realizaci. Když se nápad rozhodne udělat, dostane záznam
v [ZMENY.md](ZMENY.md) (stav „navrženo“) a tady se u něj doplní odkaz. Nejnovější nahoře.

**Stavy:** `nápad` – jen zapsáno · `pozastaveno` – rozpracovaná úvaha, čeká · `odloženo` – vědomě
na později · `převedeno` – realizuje se přes ZM-xxx · `zamítnuto` – nebude se dělat

---

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
