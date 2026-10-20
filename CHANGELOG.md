# Změny ve verzích

## 1.0.1 – 2026-10-20

- `init-env` sám zjistí IP adresu počítače (spuštění s `--network host`) a vypíše, na jaké
  adrese bude aplikace dostupná; když `--url` míří na cizí adresu, upozorní.
- `init-env --uid "$(id -u)" --gid "$(id -g)"` nastaví vlastníka záloh podle přihlášeného
  uživatele (dřív pevně 1000).
- Při nepovolené adrese ukáže aplikace českou stránku „Neplatný požadavek (400)“ s návodem
  na opravu; adresa aplikace je i v logu při startu.
- INSTALL.md: zjištění IP adresy, oprava adresy a vlastníka záloh.

Aktualizace z 1.0.0: v `.env` změnit `PRONAJMY_VERSION=1.0.1`, pak `docker compose pull`
a `docker compose up -d`. Data ani `.env` se jinak nemění.

## 1.0.0 – 2026-10-20

První vydání: demo se smyšlenými daty, čistá instalace, denní šifrované zálohy databáze
a příloh, kontrola a obnova záloh.
