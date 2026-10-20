# Pronájmy – instalace

Verze @VERZE@. Webová aplikace pro evidenci pronajímaných bytů běží u vás doma v Dockeru,
například na Raspberry Pi, a je dostupná v lokální síti z prohlížeče na počítači i mobilu.
Data zůstávají jen u vás, aplikace nic neposílá ven.

Postup má dvě části: nejdřív si vyzkoušíte **demo** se smyšlenými daty, potom nainstalujete
**čistý provoz** pro vlastní data. Obojí může běžet zároveň.

## 1. Co je potřeba

- Raspberry Pi 4 nebo 5 (doporučeno 2 GB RAM a víc) s **64bitovým** systémem, nebo jiný
  počítač s Linuxem a Dockerem. Ověření na Pi: `uname -m` musí vypsat `aarch64`
  (`armv7l` = 32bitový systém, ten nestačí).
- Docker s Compose v2: `docker compose version` vypíše verzi. Instalace na Raspberry Pi OS:
  `curl -fsSL https://get.docker.com | sh` a `sudo usermod -aG docker $USER` (pak se odhlásit
  a přihlásit).
- Pevná IP adresa Pi v domácí síti (rezervace v routeru). Zjistíte ji příkazem
  `hostname -I` (první adresa). V návodu je jako příklad `192.168.1.50` – nahraďte ji svou.
- Účet na GitHubu s přístupem ke čtení balíčku `pronajmy` (přidělí autor).

## 2. Přístup k image

Aplikace se stahuje jako hotový image z GitHub Container Registry. Jednou:

1. Na GitHubu: Settings → Developer settings → Personal access tokens → **Tokens (classic)** →
   Generate new token, zaškrtnout jen **read:packages**, platnost podle sebe.
2. Na Pi: `docker login ghcr.io -u <vaše-jméno-na-GitHubu>` a jako heslo vložit token.

## 3. Demo se smyšlenými daty

```sh
mkdir -p ~/pronajmy-demo && cd ~/pronajmy-demo     # sem zkopírujte compose.demo.yml
docker compose -f compose.demo.yml up -d
```

První start trvá několik minut (stažení image, vytvoření dat). Pak otevřete
`http://192.168.1.50:8003` a přihlaste se **demo / demo**. Data jsou vymyšlená a vztažená
k dnešku; cokoli v demu změníte, jde vrátit:

```sh
docker compose -f compose.demo.yml exec web python manage.pyc seed_demo --reset   # obnova dat
docker compose -f compose.demo.yml --profile reset up -d    # obnova každý den ve 03:00 (volitelné)
docker compose -f compose.demo.yml down -v                  # konec dema včetně jeho dat
```

## 4. Čistá instalace pro vlastní data

```sh
mkdir -p ~/pronajmy && cd ~/pronajmy                # sem zkopírujte compose.yml
mkdir backups
docker run --rm --network host ghcr.io/jemop/pronajmy:@VERZE@ init-env --uid "$(id -u)" --gid "$(id -g)" > .env
chmod 600 .env
docker compose up -d
```

- `init-env` vygeneruje `.env` s novými hesly, sám zjistí IP adresu Pi a vypíše, na jaké
  adrese bude aplikace dostupná (např. `Aplikace bude dostupná na http://192.168.1.50:8080`).
  Jinou adresu nebo port zadáte parametrem `--url http://<IP>:<port>`; když adresa nepatří
  tomuto počítači, `init-env` upozorní.
- **Ze souboru `.env` si opište mimo Pi heslo záloh `BACKUP_PASSPHRASE` a heslo účtu
  `PRONAJMY_ADMIN_PASSWORD`** (správce hesel, papír). Bez hesla záloh nejdou zálohy obnovit.
- Otevřete vypsanou adresu, přihlaste se jménem `spravce` a heslem z `.env`
  a hned si heslo změňte (kliknutím na jméno v horní liště). Heslo v `.env` se pak už
  nepoužívá a aplikace ho nikdy nepřepíše.
- Na Přehledu vás provedou **První kroky**: účet, byt, nájemník, smlouva. Výchozí účely
  a druhy revizí jsou připravené.

Aplikace je dostupná jen na adrese `PRONAJMY_URL` z `.env` (vypíše ji i
`docker compose logs web | grep dostupná`). Jinou adresu (např. `raspberrypi.local`) doplňte
do `.env` řádkem `DJANGO_ALLOWED_HOSTS=raspberrypi.local` a spusťte
`docker compose up -d --force-recreate web`.

Spojení v domácí síti je po HTTP (nešifrované). Aplikaci proto nezpřístupňujte z internetu
(žádné přesměrování portu na routeru).

## 5. Zálohy

Služba `backup` každý den ve 02:45 uloží do složky `backups/` dva zašifrované soubory:
`db_RRRR-MM-DD_HHMM.dump.enc` (databáze) a `media_RRRR-MM-DD_HHMM.tar.enc` (přílohy).
Zálohy starší 30 dní maže. Čas a počet dní jsou v `.env` (`BACKUP_TIME`, `BACKUP_RETENTION_DAYS`).

**Zálohy leží na stejné kartě / disku jako data.** Kopírujte složku `backups/` pravidelně
jinam (NAS, jiný počítač, USB disk) – např. `rsync -a ~/pronajmy/backups/ nas:/zalohy/pronajmy/`
z cronu.

```sh
docker compose exec backup /bin/sh /backup.sh now                                       # ruční záloha
docker compose exec backup /bin/sh /restore.sh check /backups/db_<čas>.dump.enc          # kontrola DB
docker compose exec backup /bin/sh /restore.sh media-check /backups/media_<čas>.tar.enc  # kontrola příloh
```

`check` obnoví zálohu do dočasné databáze, vypíše počty (pohyby, byty, smlouvy, platby,
přílohy) vedle provozních a dočasnou databázi smaže – provozní data se nemění.

### Obnova ze zálohy

```sh
docker compose stop web
docker compose exec backup /bin/sh /restore.sh restore /backups/db_<čas>.dump.enc
docker compose exec backup /bin/sh /restore.sh media-restore /backups/media_<čas>.tar.enc
docker compose start web
```

### Přenos na jiný počítač

1. Na novém počítači body 1 a 2, složka `~/pronajmy` s `compose.yml`, **původním `.env`**
   (nespouštějte `init-env` – zálohy jsou zašifrované heslem z původního `.env`) a složkou
   `backups/` se zálohami. Pokud se změnila IP adresa, upravte v `.env` `PRONAJMY_URL`.
2. `docker compose up -d db backup`
3. Obnova databáze a příloh podle předchozího odstavce (`restore`, `media-restore`).
4. `docker compose up -d`

## 6. Aktualizace na novou verzi

Co je v nové verzi, popisuje `CHANGELOG.md` v instalačním balíčku.

```sh
cd ~/pronajmy
docker compose exec backup /bin/sh /backup.sh now    # záloha před aktualizací
# v .env změnit PRONAJMY_VERSION na novou verzi
docker compose pull
docker compose up -d                                 # úpravy databáze proběhnou při startu
```

Verze, která běží, je vidět v patičce aplikace. Návrat k předchozí verzi: původní číslo
v `PRONAJMY_VERSION` a obnova zálohy pořízené před aktualizací.

## 7. Odinstalace

```sh
cd ~/pronajmy && docker compose down       # zastavení, data zůstanou
docker compose down -v                     # zastavení a SMAZÁNÍ databáze a příloh
```

Složka `backups/` se nemaže – zálohy smažte ručně, až je nebudete potřebovat.

## 8. Osobní údaje

V aplikaci evidujete údaje svých nájemníků; za jejich zpracování odpovídáte jako
pronajímatel. Aplikace ukládá jen nezbytné údaje (bez rodného čísla a čísla dokladu),
kontakty nedává do exportů a nic neposílá mimo váš počítač.

## Když něco nejde

- Stav služeb: `docker compose ps`, logy aplikace: `docker compose logs web`, záloh:
  `docker compose logs backup`.
- „Neplatný požadavek (400)“ – adresa v prohlížeči se liší od `PRONAJMY_URL` v `.env`.
  Oprava: `sed -i 's#^PRONAJMY_URL=.*#PRONAJMY_URL=http://<IP>:8080#' .env` a
  `docker compose up -d --force-recreate web` (viz konec bodu 4).
- Soubory v `backups/` nejdou smazat – v `.env` nesedí `BACKUP_UID` / `BACKUP_GID` s výstupem
  `id -u` / `id -g`; opravte je a spusťte `docker compose up -d --force-recreate backup`.
- `unauthorized` při stahování image – chybí `docker login ghcr.io` nebo přístup k balíčku.
- `no matching manifest for linux/arm/v7` – na Pi běží 32bitový systém (bod 1).
