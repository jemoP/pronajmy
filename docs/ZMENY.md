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

## ZM-009 – Hromadné mazání pohybů
- **Datum:** 2026-10-19
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** více označených pohybů má jít smazat jedním příkazem.
- **Popis:** v Pohybech jde označit každý pohyb (i převody, výběry a vklady); panel označených nabízí změnu účelu a smazání. Smazání vede na potvrzovací stránku se součty po druzích, seznamem pohybů, dopady (platby ke smlouvám se smažou s upozorněním na saldo, splátky plateb dodavatelům se znovu otevřou, opravy a revize přijdou o zapsaný náklad) a exportem označených do CSV. Vše, nebo nic; změněné pohyby mezi označením a potvrzením potvrzení odmítnou. Rozsah nejvýš jedna stránka seznamu.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Pravidla pohybů – hromadné smazání, Funkční požadavky P02).
- **Dopad na data:** žádný (beze změny schématu).
- **Implementováno:** 2026-10-19, větev feature/zm-009

## ZM-008 – Oddělený výsledek nájmu a služeb
- **Datum:** 2026-10-19
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** porovnat příjem z nájmu s náklady mimo služby a zvlášť příjmy ze služeb (zálohy, vyúčtování) s náklady na služby.
- **Popis:** účel má příznak „Služba (průběžná položka)“ (výchozí: Zálohy na služby, Vyúčtování služeb, Služby a energie; jde nastavit i u vlastních účelů). Výsledek se všude dělí na zisk z nájmu a rozdíl služeb (celkem beze změny): Výkaz (dlaždice, po bytech ve dvou blocích, měsíce, roky, graf nájmu, export), Přehled a karta bytu. Přehled služeb (ZM-007) se řídí příznakem místo pevných kódů. Pohyby a podklad pro daně beze změny. Fond oprav / SVJ patří do nájmu.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Datový model – `category`, Pravidla pohybů – výsledek, Služby a energie, Funkční požadavky P12).
- **Dopad na data:** nový sloupec `category.is_service` (výchozí ne), datová migrace ho zapne u kódů SERVICES, SETTLEMENT, UTILITIES, ELECTRICITY, GAS, WATER_COLD, WATER_HOT, HEATING.
- **Implementováno:** 2026-10-19, větev feature/zm-008

## ZM-007 – Náklady na energie a přehled služeb
- **Datum:** 2026-10-18
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** sledovat náklady na elektřinu, plyn, teplou a studenou vodu a vytápění zvlášť a porovnat je se zálohami od nájemníků (podklad pro vyúčtování služeb).
- **Popis:** výchozí nákladové účely Elektřina, Plyn, Studená voda, Teplá voda, Vytápění (mimo daně, s kódem). Ve Výkazu záložka Služby: pro rok a byt tabulka měsíců × energie a ostatní služby proti zálohám na služby, rozdíl (krytí záloh), srovnání s loňskem, export CSV / XLSX. V Pohybech hromadná změna účelu označených pohybů (např. převod dosavadních „Služeb“ na konkrétní energie).
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Datový model – výchozí účely a kódy, Funkční požadavky P02, P12).
- **Dopad na data:** datová migrace přidá 5 účelů (existující účel stejného názvu dostane kód); schéma beze změny.
- **Implementováno:** 2026-10-18, větev feature/zm-007

## ZM-006 – Předpisy plateb dodavatelům
- **Datum:** 2026-10-18
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** opakované platby dodavatelům (energie, plyn, voda, fond oprav SVJ, SIPO) se zadávají ručně; z předpisu s platností v čase má jít vygenerovat pohyb.
- **Popis:** nová stránka Platby. Předpis platby (dodavatel, způsob platby, účet, četnost, den splatnosti, platnost od–do) s rozpisem na řádky (účel, byt, částka – např. SVJ: fond oprav, správa, zálohy na služby). Z předpisu vznikají splátky do aktuálního měsíce; zaplacení tlačítkem nebo dávkově vytvoří z každého řádku náklad. Výchozí je zápis k potvrzení, přepínač v předpisu zapne automatický zápis k datu splatnosti. Změna od data založí navazující předpis. Seznam K zaplacení, výhled na 12 měsíců, sekce na kartě bytu, upozornění.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Datový model – Platby dodavatelům, Funkční požadavky P17).
- **Dopad na data:** nové tabulky `payable`, `payable_item`, `payable_due`; nový sloupec `entry.payable_due_id`.
- **Implementováno:** 2026-10-18, větev feature/zm-006

## ZM-005 – Platba z předpisu (jednotlivě i dávkově)
- **Datum:** 2026-10-17
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** zaplacení konkrétního předpisu má jít zapsat jedním kliknutím a víc předpisů najednou, každý jako samostatnou platbu; tabulka předpisů má ukazovat, který předpis je zaplacený kterou platbou.
- **Popis:** v tabulce předpisů na smlouvě tlačítko „Zaplaceno“ u otevřeného předpisu a zaškrtávátka pro dávkové zapsání. Z každého předpisu vznikne samostatný příjem na nezaplacenou část s vazbou na předpis (účel podle druhu předpisu, jistota jako Jistota), datum podle splatnosti (nejpozději dnes) nebo jedno zvolené. Platba s vazbou kryje nejdřív svůj předpis, zbytek salda dál FIFO; celkové saldo se nemění. Zápis jedné částky rozdělené FIFO zůstává.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Datový model – `rent_payment`, Pravidla pronájmů – Saldo, Platba z předpisu, Funkční požadavky P06).
- **Dopad na data:** nový sloupec `rent_payment.charge_id` (NULL, při smazání předpisu SET NULL); existující platby zůstávají bez vazby (FIFO).
- **Implementováno:** 2026-10-17, větev feature/zm-005

## ZM-004 – Služby mimo podklad pro daně
- **Datum:** 2026-10-17
- **Stav:** hotovo
- **Zadal:** Petr
- **Důvod:** zálohy na služby nájemník platí za služby, které pronajímatel jen přeposílá dodavatelům; do příjmů z nájmu pro daně nepatří.
- **Popis:** účel má příznak „počítat do daní“ (`taxable`). Výchozí účely Zálohy na služby, Vyúčtování služeb (nedoplatky i vrácené přeplatky) a náklad Služby ho mají vypnutý, ostatní zapnutý; u každého účelu jde změnit v Číselníky › Účely. Podklad pro daňové přiznání (P13) počítá příjmy, skutečné výdaje i paušál jen z účelů s příznakem a ukazuje, kolik bylo vyřazeno. Výkaz a výsledek se nemění.
- **Dotčené kapitoly:** ZADANI-PRONAJMY.md (Datový model – Peníze, Funkční požadavky P13).
- **Dopad na data:** nový sloupec `category.taxable` (výchozí ano), datová migrace vypne příznak u kódů SERVICES, SETTLEMENT a UTILITIES.
- **Implementováno:** 2026-10-17, větev feature/etapa-4

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
