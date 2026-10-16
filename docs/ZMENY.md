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

## ZM-001 – Založení projektu
- **Datum:** 2026-10-16
- **Stav:** schváleno
- **Zadal:** Petr
- **Důvod:** evidence pronájmů se oddělila od HomeFinance do samostatné aplikace s vlastními daty (HomeFinance ZM-012; dřívější verze uvnitř HomeFinance je archivovaná pod tagem `etapa-8-archiv`).
- **Popis:** výchozí zadání `docs/ZADANI-PRONAJMY.md` a `CLAUDE.md` převzaté z HomeFinance (commit 0a9ae32). Rozhodnutí z HomeFinance ZM-012: data naprosto oddělená, historie účelů 59 a 62 se neimportuje (historické smlouvy se zadají ručně), zůstatek pronájmů se do majetku HomeFinance nepřenáší.
- **Dotčené kapitoly:** celé zadání (výchozí verze).
- **Dopad na data:** nová databáze.
- **Implementováno:** etapa 0 (kostra) 2026-10-16, větev feature/etapa-0; další etapy průběžně
