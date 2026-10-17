# Historie změn zadání

Každá změna zadání (`docs/ZADANI-PRONAJMY.md`) má vlastní záznam. Nejnovější nahoře.

**Stavy:**
- `navrženo` – změna je popsaná, čeká na rozhodnutí
- `schváleno` – rozhodnuto, čeká na implementaci
- `hotovo` – naprogramováno a otestováno
- `zamítnuto` – nebude se dělat (ponechat kvůli historii)

---

## Šablona záznamu

```
## ZM-000 – Krátký název změny
- **Datum:** RRRR-MM-DD
- **Stav:** navrženo
- **Zadal:** jméno / role
- **Důvod:** proč je změna potřeba
- **Popis:** co se mění z pohledu uživatele
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (kapitola)
- **Dopad na data:** nové tabulky/pole, migrace existujících dat
- **Implementováno:** RRRR-MM-DD, větev / commit
```

---

## ZM-003 – Vrácení přeplatku snižuje příjmy
- **Datum:** 2026-10-17
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** vrácený přeplatek zapsaný jako náklad nadsazuje příjmy i náklady; podklad pro daňové přiznání (P13) by počítal paušál 30 % z vyšších příjmů.
- **Popis:** náklad (EXPENSE) smí mít účel druhu příjem – jde o vrácení příjmu. Ve výsledku se odečte od příjmů, do nákladů se nepočítá. Vrácení přeplatku nájemníkovi se zapisuje jako náklad s účelem Vyúčtování služeb.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Pravidla pohybů, Pravidla pronájmů – Zápis platby), CLAUDE.md (Doména).
- **Dopad na data:** žádný (beze změny schématu).
- **Implementováno:** 2026-10-17, větev feature/etapa-2

## ZM-002 – Interní kód účelu, byty už v etapě 1
- **Datum:** 2026-10-16
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** pravidla (byt volitelný u ostatních příjmů / nákladů, rozdělení platby na nájemné, zálohy a jistotu, výdaj opravy a revize) potřebují najít výchozí účel spolehlivě i po přejmenování. Pohyb má povinný byt už v etapě 1, byty ale patřily až do etapy 2.
- **Popis:** účel má interní `code`; výchozí účely ho dostanou v datové migraci, účel s kódem nejde smazat ani změnit jeho druh. Model bytu a jeho jednoduchá správa (seznam, formulář) se přesouvají do etapy 1; karta bytu zůstává v etapě 2.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Datový model – Peníze, Etapy a akceptace).
- **Dopad na data:** nový sloupec `category.code` (unikátní, NULL u vlastních účelů).
- **Implementováno:** 2026-10-16, větev feature/etapa-1 (etapa 1)

## ZM-001 – Založení projektu
- **Datum:** 2026-10-16
- **Stav:** schváleno
- **Zadal:** Petr
- **Důvod:** evidence pronájmů se oddělila od HomeFinance do samostatné aplikace s vlastními daty (HomeFinance ZM-012; dřívější verze uvnitř HomeFinance je archivovaná pod tagem `etapa-8-archiv`).
- **Popis:** výchozí zadání `docs/ZADANI-PRONAJMY.md` a `CLAUDE.md` převzaté z HomeFinance (commit 0a9ae32). Rozhodnutí z HomeFinance ZM-012: data naprosto oddělená, historie účelů 59 a 62 se neimportuje (historické smlouvy se zadají ručně), zůstatek pronájmů se do majetku HomeFinance nepřenáší.
- **Dotčené kapitoly:** celé zadání (výchozí verze).
- **Dopad na data:** nová databáze.
- **Implementováno:** etapa 0 (kostra) 2026-10-16, větev feature/etapa-0; další etapy průběžně
