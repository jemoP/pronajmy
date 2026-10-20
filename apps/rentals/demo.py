"""Smyšlená data pro demo (ZM-010, P19).

Data vznikají přes stejné služby jako v aplikaci (předpisy, platby, jistoty, opravy, revize,
platby dodavatelům), takže vazby, saldo i výkaz odpovídají běžnému používání. Vše je
relativní k dnešku a opakovatelné (pevné semínko). Jména, adresy, telefony, e-maily i čísla
účtů jsou vymyšlené (@example.cz, 600 000 xxx).
"""

import random
import shutil
import struct
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django.apps import apps as global_apps
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection, models, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython
from django.utils import timezone

from apps.core.dates import add_months
from apps.money.models import (
    Account,
    AccountKind,
    CategoryCode,
    Entry,
    EntryKind,
    Payable,
    PaymentMethod,
)
from apps.money.services.entries import EntryInput, create_entry
from apps.money.services.payables import ItemInput, ensure_dues, open_dues, pay_dues, save_payable
from apps.rentals.models import (
    Attachment,
    Channel,
    ChargeKind,
    Communication,
    Direction,
    Inspection,
    InspectionPlan,
    InspectionResult,
    InspectionType,
    Lease,
    LeaseAmendment,
    LeaseStatus,
    PaidBy,
    PaymentKind,
    Property,
    RentCharge,
    Repair,
    RepairStatus,
    Tenant,
)
from apps.rentals.services.attachments import add_attachment
from apps.rentals.services.charges import ensure_all_charges, ensure_charges, month_start
from apps.rentals.services.leases import save_amendment, save_lease
from apps.rentals.services.maintenance import save_inspection, save_repair
from apps.rentals.services.payments import (
    category_id,
    end_with_settlement,
    offset_deposit,
    pay_charges,
    pay_out,
    record_payment,
)

DEMO_USER = "demo"
DEMO_PASSWORD = "demo"
HISTORY_MONTHS = 36
SEED = 2026
# Aplikace s výchozími daty v datových migracích (účely, druhy revizí).
DEFAULT_DATA_APPS = ("money", "rentals")


def demo_database_ok() -> bool:
    """Pojistka: demo smí běžet jen nad databází s „demo“ v názvu."""
    return "demo" in str(connection.settings_dict["NAME"]).lower()


def has_data() -> bool:
    return User.objects.exists() or Property.objects.exists() or Entry.objects.exists()


def kc(korun: int) -> int:
    return korun * 100


# --- Obnova -------------------------------------------------------------------


def reset_database() -> None:
    """Vymaže všechna data (vč. uživatelů, sezení a admin logu) a přílohy a vrátí výchozí
    číselníky z datových migrací."""
    call_command("flush", interactive=False, verbosity=0)
    restore_defaults()
    clear_media()


def restore_defaults() -> None:
    """Znovu spustí datové migrace aplikací (výchozí účely, druhy revizí) v pořadí migrací."""
    loader = MigrationLoader(connection)
    leaves = [node for node in loader.graph.leaf_nodes() if node[0] in DEFAULT_DATA_APPS]
    with transaction.atomic(), connection.schema_editor() as schema_editor:
        for key in _plan(loader, leaves):
            migration = loader.graph.nodes[key]
            for operation in migration.operations:
                if isinstance(operation, RunPython):
                    # Funkce datových migrací používají jen get_model – stačí běžný registr.
                    operation.code(global_apps, schema_editor)  # type: ignore[arg-type]


def _plan(loader: MigrationLoader, leaves: list[tuple[str, str]]) -> list[tuple[str, str]]:
    plan: list[tuple[str, str]] = []
    for leaf in leaves:
        for key in loader.graph.forwards_plan(leaf):
            if key[0] in DEFAULT_DATA_APPS and key not in plan:
                plan.append(key)
    return plan


def clear_media() -> None:
    root = Path(settings.MEDIA_ROOT)
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


# --- Ukázkové přílohy ---------------------------------------------------------


def sample_pdf(title: str) -> bytes:
    """Jednostránkové PDF s textem (jen ASCII – standardní písmo Helvetica)."""
    stream = (
        f"BT /F1 20 Tf 60 760 Td ({title}) Tj 0 -30 Td /F1 12 Tf"
        " (Ukazkova priloha - demo, smyslena data) Tj ET"
    ).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def sample_png(width: int = 240, height: int = 160) -> bytes:
    """Jednoduchý obrázek PNG (světlé pozadí s tmavším pruhem)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = bytearray()
    for y in range(height):
        rows.append(0)
        color = (71, 85, 105) if height // 3 <= y < height // 3 + 24 else (226, 232, 240)
        rows += bytes(color) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def attach(owner_field: str, owner: models.Model, name: str, content: bytes) -> None:
    add_attachment(owner_field, owner, SimpleUploadedFile(name, content))


# --- Generátor ----------------------------------------------------------------


@dataclass(frozen=True)
class DemoSummary:
    properties: int
    leases: int
    entries: int
    attachments: int


class _Builder:
    def __init__(self, today: date) -> None:
        self.today = today
        self.start = add_months(month_start(today), -HISTORY_MONTHS)
        self.rng = random.Random(SEED)

    # Pomocné ------------------------------------------------------------------

    def day_before(self, day: date, max_days: int) -> date:
        """Den o 0–max_days dříve (platby chodí kolem splatnosti), nejpozději dnes."""
        return min(day - timedelta(days=self.rng.randint(0, max_days)), self.today)

    def at(self, day: date, hour: int = 10) -> datetime:
        return timezone.make_aware(datetime.combine(day, time(hour, 0)))

    def due_months(self, lease: Lease) -> list[date]:
        """Měsíce s předpisem nájmu se splatností do dneška."""
        ensure_charges(lease, self.today)
        rows = lease.charges.filter(
            kind=ChargeKind.RENT, period__isnull=False, due_date__lte=self.today
        ).order_by("period")
        return [row.period for row in rows if row.period]

    def pay_month(self, lease: Lease, month: date) -> None:
        """„Zaplaceno“ z předpisů měsíce (nájem i zálohy)."""
        charges = list(lease.charges.filter(period=month).order_by("kind"))
        due = charges[0].due_date
        pay_charges(
            lease,
            [c.pk for c in charges],
            day=max(self.day_before(due, 4), lease.start_date),
            account_id=self.bank.pk,
            today=self.today,
        )

    def month_total(self, lease: Lease, month: date) -> int:
        """Předpis měsíce (nájem + zálohy) v Kč – po dodatku se mění."""
        return sum(c.amount_cents for c in lease.charges.filter(period=month)) // 100

    def pay_deposit(self, lease: Lease) -> None:
        charge = lease.charges.get(kind=ChargeKind.DEPOSIT)
        pay_charges(
            lease, [charge.pk], day=charge.due_date, account_id=self.bank.pk, today=self.today
        )

    def lease(self, prop: Property, main: Tenant, co: list[Tenant], **fields: object) -> Lease:
        lease = Lease(property=prop, account=self.bank, **fields)
        return save_lease(lease, main, co)

    def entry(self, day: date, kind: str, korun: int, note: str, **fields: object) -> Entry:
        return create_entry(
            EntryInput(date=day, kind=kind, amount_cents=kc(korun), note=note, **fields)  # type: ignore[arg-type]
        )

    # Části dema ------------------------------------------------------------------

    def run(self) -> DemoSummary:
        user = User.objects.create_user(DEMO_USER, password=DEMO_PASSWORD)
        user.first_name = "Demo"
        user.save(update_fields=["first_name"])
        self.accounts()
        self.properties()
        self.tenants()
        self.lease_lipova()
        self.leases_vysluni()
        self.lease_zahradni()
        self.maintenance()
        self.communication()
        self.payables()
        self.household()
        ensure_all_charges(self.today)
        ensure_dues(self.today)
        return DemoSummary(
            properties=Property.objects.count(),
            leases=Lease.objects.count(),
            entries=Entry.objects.count(),
            attachments=Attachment.objects.count(),
        )

    def accounts(self) -> None:
        self.bank = Account.objects.create(
            name="Účet pronájmů",
            kind=AccountKind.BANK,
            bank_code="0800",
            account_number="2001234567",
        )
        self.savings = Account.objects.create(
            name="Spořicí účet pronájmů",
            kind=AccountKind.BANK,
            bank_code="0800",
            account_number="2009876543",
        )
        self.entry(
            self.start,
            EntryKind.DEPOSIT,
            50_000,
            "Počáteční vklad z domácnosti",
            account_id=self.bank.pk,
        )

    def properties(self) -> None:
        def prop(
            name: str, address: str, unit: str, layout: str, area: str, note: str = ""
        ) -> Property:
            return Property.objects.create(
                name=name,
                address=address,
                unit=unit,
                layout=layout,
                floor_area=Decimal(area) if area else None,
                account=self.bank,
                note=note,
            )

        self.lipova = prop("Lipová 12", "Lipová 12, 602 00 Brno", "12/5", "2+kk", "54.3")
        self.vysluni = prop("Na Výsluní 7", "Na Výsluní 7, 612 00 Brno", "7/12", "3+1", "78.6")
        self.zahradni = prop("Zahradní 3", "Zahradní 3, 664 51 Šlapanice", "3/2", "1+1", "38.0")
        self.garaz = prop(
            "Garáž Polní", "Polní 40, 664 51 Šlapanice", "G-4", "", "", "Zatím bez nájemce."
        )

    def tenants(self) -> None:
        def tenant(name: str, login: str, phone: str, born: date) -> Tenant:
            return Tenant.objects.create(
                name=name, email=f"{login}@example.cz", phone=phone, birth_date=born
            )

        self.vzorova = tenant("Lucie Vzorová", "lucie.vzorova", "600 000 101", date(1990, 4, 12))
        self.priklad = tenant("Ondřej Příklad", "ondrej.priklad", "600 000 102", date(1984, 9, 3))
        self.ukazka = tenant("Martin Ukázka", "martin.ukazka", "600 000 103", date(1995, 1, 27))
        self.ukazkova = tenant(
            "Tereza Ukázková", "tereza.ukazkova", "600 000 104", date(1996, 6, 8)
        )
        self.testova = tenant("Eva Testová", "eva.testova", "600 000 105", date(1999, 11, 30))
        self.novackova = tenant(
            "Klára Nováčková", "klara.novackova", "600 000 106", date(2001, 2, 14)
        )

    def lease_lipova(self) -> None:
        """Dlouhodobá smlouva s dodatkem, platby „Zaplaceno“, vyúčtování služeb."""
        start = self.start
        lease = self.lease(
            self.lipova,
            self.vzorova,
            [],
            number=f"{start.year}/01",
            signed_date=start - timedelta(days=10),
            start_date=start,
            rent_cents=kc(14_000),
            services_cents=kc(3_000),
            due_day=5,
            deposit_cents=kc(34_000),
            variable_symbol=f"{start.year}01",
            status=LeaseStatus.ACTIVE,
        )
        effective = add_months(month_start(self.today), -10)
        amendment = save_amendment(
            LeaseAmendment(
                lease=lease,
                number="1",
                signed_date=effective - timedelta(days=21),
                effective_date=effective,
                description="Zvýšení nájmu o míru inflace.",
                rent_cents=kc(15_000),
            )
        )
        ensure_charges(lease, self.today)
        self.pay_deposit(lease)
        for month in self.due_months(lease):
            self.pay_month(lease, month)

        # Vyúčtování služeb: přeplatek vrácený nájemnici, o rok později nedoplatek.
        refund_day = add_months(start, 16).replace(day=20)
        pay_out(
            lease,
            kind=PaymentKind.REFUND,
            day=refund_day,
            amount=kc(2_350),
            account_id=self.bank.pk,
            note=f"Přeplatek z vyúčtování služeb {refund_day.year - 1}",
            today=self.today,
        )
        due = add_months(start, 28).replace(day=15)
        charge = RentCharge.objects.create(
            lease=lease,
            kind=ChargeKind.SETTLEMENT,
            due_date=due,
            amount_cents=kc(1_860),
            manual=True,
            note=f"Nedoplatek vyúčtování {due.year - 1}",
        )
        pay_charges(
            lease,
            [charge.pk],
            day=due + timedelta(days=3),
            account_id=self.bank.pk,
            today=self.today,
        )
        attach(
            "lease", lease, "najemni-smlouva-lipova.pdf", sample_pdf("Najemni smlouva - Lipova 12")
        )
        attach(
            "amendment", amendment, "dodatek-1-lipova.pdf", sample_pdf("Dodatek c. 1 - Lipova 12")
        )
        self.lease_lipova_obj = lease

    def leases_vysluni(self) -> None:
        """Ukončená smlouva (započtení a vrácení jistoty) a nová se spolunájemcem a dluhem."""
        start = self.start
        old = self.lease(
            self.vysluni,
            self.priklad,
            [],
            number=f"{start.year}/02",
            signed_date=start - timedelta(days=14),
            start_date=start,
            rent_cents=kc(18_000),
            services_cents=kc(4_000),
            due_day=5,
            deposit_cents=kc(44_000),
            variable_symbol=f"{start.year}02",
            status=LeaseStatus.ACTIVE,
        )
        end = add_months(start, 21) - timedelta(days=1)
        end_with_settlement(
            old, end, "Výpověď nájemce – stěhování za prací", today=self.today, confirm=True
        )
        ensure_charges(old, self.today)
        self.pay_deposit(old)
        months = self.due_months(old)
        for month in months[:-1]:  # poslední měsíc nájemce nezaplatil
            self.pay_month(old, month)
        offset_deposit(
            old,
            day=end + timedelta(days=5),
            amount=kc(22_000),
            note="Započtení na nezaplacený nájem za poslední měsíc",
        )
        pay_out(
            old,
            kind=PaymentKind.DEPOSIT_RETURN,
            day=end + timedelta(days=12),
            amount=kc(22_000),
            account_id=self.bank.pk,
            note="Vrácení zbytku jistoty",
            today=self.today,
        )
        self.entry(
            end + timedelta(days=3),
            EntryKind.EXPENSE,
            1_490,
            "Inzerce pronájmu – Na Výsluní 7",
            account_id=self.bank.pk,
            category_id=category_id(CategoryCode.MANAGEMENT),
            property_id=self.vysluni.pk,
        )
        save_repair(
            Repair(
                property=self.vysluni,
                lease=old,
                reported_date=end + timedelta(days=1),
                title="Vymalování po nájemci",
                status=RepairStatus.DONE,
                contractor="Malířství Štětec",
                done_date=end + timedelta(days=14),
                cost_cents=kc(9_800),
                paid_by=PaidBy.OWNER,
            ),
            account_id=self.bank.pk,
            today=self.today,
        )

        new_start = month_start(add_months(end, 2))
        new = self.lease(
            self.vysluni,
            self.ukazka,
            [self.ukazkova],
            number=f"{new_start.year}/03",
            signed_date=new_start - timedelta(days=12),
            start_date=new_start,
            rent_cents=kc(19_500),
            services_cents=kc(4_200),
            due_day=5,
            deposit_cents=kc(47_400),
            variable_symbol=f"{new_start.year}03",
            status=LeaseStatus.ACTIVE,
        )
        # Po vyúčtování služeb vyšší zálohy.
        effective = add_months(month_start(self.today), -4)
        services = save_amendment(
            LeaseAmendment(
                lease=new,
                number="1",
                signed_date=effective - timedelta(days=15),
                effective_date=effective,
                description="Zvýšení záloh na služby po vyúčtování.",
                services_cents=kc(4_600),
            )
        )
        ensure_charges(new, self.today)
        self.pay_deposit(new)
        months = self.due_months(new)
        paid = months[:-2]  # poslední dva měsíce nezaplacené – dluh
        partial = 15_000
        for index, month in enumerate(paid):
            due = new.charges.filter(period=month).first()
            assert due is not None
            day = max(self.day_before(due.due_date, 3), new.start_date)
            amount = self.month_total(new, month)
            if index == 4:
                amount = partial  # částečná platba
            elif index == 5:
                # doplatek s dalším měsícem
                amount += self.month_total(new, paid[4]) - partial
            record_payment(
                new,
                day=day,
                amount=kc(amount),
                account_id=self.bank.pk,
                note="Platba převodem",
                today=self.today,
            )
        attach(
            "lease",
            new,
            "najemni-smlouva-vysluni.pdf",
            sample_pdf("Najemni smlouva - Na Vysluni 7"),
        )
        attach(
            "amendment",
            services,
            "dodatek-1-vysluni.pdf",
            sample_pdf("Dodatek c. 1 - Na Vysluni 7"),
        )
        self.lease_vysluni_obj = new
        self.lease_vysluni_old = old
        self.old_end = end

    def lease_zahradni(self) -> None:
        """Smlouva na dobu určitou prodloužená dodatkem, končící do 60 dní, a návrh
        navazující smlouvy."""
        start = add_months(month_start(self.today), -23)
        first_end = add_months(start, 12) - timedelta(days=1)
        end = self.today + timedelta(days=45)
        lease = self.lease(
            self.zahradni,
            self.testova,
            [],
            number=f"{start.year}/04",
            signed_date=start - timedelta(days=7),
            start_date=start,
            end_date=first_end,
            rent_cents=kc(11_500),
            services_cents=kc(2_500),
            due_day=10,
            deposit_cents=kc(23_000),
            variable_symbol=f"{start.year}04",
            status=LeaseStatus.ACTIVE,
        )
        prolonged = save_amendment(
            LeaseAmendment(
                lease=lease,
                number="1",
                signed_date=first_end - timedelta(days=40),
                effective_date=first_end - timedelta(days=30),
                description="Prodloužení nájmu do "
                f"{end.day}. {end.month}. {end.year}, ostatní podmínky beze změny.",
                end_date=end,
            )
        )
        attach(
            "amendment",
            prolonged,
            "dodatek-1-zahradni.pdf",
            sample_pdf("Dodatek c. 1 - Zahradni 3 - prodlouzeni"),
        )
        ensure_charges(lease, self.today)
        self.pay_deposit(lease)
        for month in self.due_months(lease):
            due = lease.charges.filter(period=month).first()
            assert due is not None
            record_payment(
                lease,
                day=max(self.day_before(due.due_date, 2), lease.start_date),
                amount=kc(self.month_total(lease, month)),
                account_id=self.bank.pk,
                note="Platba převodem",
                today=self.today,
            )
        self.lease(
            self.zahradni,
            self.novackova,
            [],
            number=f"{end.year}/05",
            start_date=end + timedelta(days=1),
            rent_cents=kc(12_500),
            services_cents=kc(2_600),
            due_day=10,
            deposit_cents=kc(25_000),
            variable_symbol=f"{end.year}05",
            status=LeaseStatus.DRAFT,
            note="Návrh – čeká na podpis.",
        )
        self.lease_zahradni_obj = lease

    def maintenance(self) -> None:
        today = self.today
        reported = add_months(today, -8)
        save_repair(
            Repair(
                property=self.lipova,
                lease=self.lease_lipova_obj,
                reported_date=reported,
                reported_by="Lucie Vzorová",
                title="Kapající baterie v koupelně",
                status=RepairStatus.DONE,
                contractor="Instalatérství Kapka",
                done_date=reported + timedelta(days=5),
                cost_cents=kc(1_850),
                paid_by=PaidBy.OWNER,
            ),
            account_id=self.bank.pk,
            today=today,
        )
        socket = save_repair(
            Repair(
                property=self.vysluni,
                lease=self.lease_vysluni_obj,
                reported_date=today - timedelta(days=6),
                reported_by="Martin Ukázka",
                title="Nefunkční zásuvka v kuchyni",
                description="Zásuvka u linky nefunguje, jistič neshazuje.",
                status=RepairStatus.ORDERED,
                contractor="Elektro Jiskra",
                paid_by=PaidBy.OWNER,
            ),
            account_id=None,
            today=today,
        )
        attach("repair", socket, "zasuvka-foto.png", sample_png())
        window = add_months(today, -5)
        save_repair(
            Repair(
                property=self.zahradni,
                lease=self.lease_zahradni_obj,
                reported_date=window,
                reported_by="Eva Testová",
                title="Rozbité okenní sklo",
                description="Poškozeno nájemnicí, oprava na její náklady.",
                status=RepairStatus.DONE,
                contractor="Sklenářství Tabule",
                done_date=window + timedelta(days=9),
                cost_cents=kc(3_200),
                paid_by=PaidBy.TENANT,
            ),
            account_id=None,
            today=today,
        )

        def plan(
            prop: Property, type_name: str, device: str, first_due: date | None = None
        ) -> InspectionPlan:
            return InspectionPlan.objects.create(
                property=prop,
                type=InspectionType.objects.get(name=type_name),
                device=device,
                first_due_date=first_due,
            )

        boiler = plan(self.lipova, "Servis plynového kotle", "Plynový kotel v koupelně")
        next_due = today + timedelta(days=16)
        last = None
        for years_back in (2, 1):
            last = save_inspection(
                Inspection(
                    plan=boiler,
                    done_date=add_months(next_due, -12 * years_back),
                    result=InspectionResult.OK,
                    contractor="Servis Teplo",
                    cost_cents=kc(1_650),
                ),
                account_id=self.bank.pk,
            )
        assert last is not None
        attach(
            "inspection", last, "servis-kotle-protokol.pdf", sample_pdf("Protokol - servis kotle")
        )

        electro = plan(self.vysluni, "Revize elektroinstalace", "Byt – rozvaděč a zásuvky")
        save_inspection(
            Inspection(
                plan=electro,
                done_date=add_months(today, -60) - timedelta(days=30),
                result=InspectionResult.DEFECTS,
                contractor="Revize Volt",
                note="Drobné závady odstraněny na místě.",
            ),
            account_id=None,
        )
        gas = plan(self.zahradni, "Revize plynového zařízení", "Plynový sporák")
        save_inspection(
            Inspection(
                plan=gas,
                done_date=add_months(self.start, 2),
                result=InspectionResult.OK,
                contractor="Plyn Servis",
                cost_cents=kc(2_400),
            ),
            account_id=self.bank.pk,
        )
        plan(
            self.garaz,
            "Kontrola hasicího přístroje",
            "Hasicí přístroj u vrat",
            today + timedelta(days=120),
        )

    def communication(self) -> None:
        today = self.today

        def note(prop: Property, lease: Lease, tenant: Tenant, day: date, **fields: object) -> None:
            Communication.objects.create(
                property=prop,
                lease=lease,
                tenant=tenant,
                occurred_at=self.at(day),
                **fields,
            )

        note(
            self.vysluni,
            self.lease_vysluni_obj,
            self.ukazka,
            today - timedelta(days=10),
            channel=Channel.EMAIL,
            direction=Direction.OUT,
            subject="Upomínka – nezaplacený nájem",
            text="Připomínka dvou nezaplacených měsíců, prosba o úhradu do týdne.",
            follow_up_date=today - timedelta(days=3),
        )
        note(
            self.zahradni,
            self.lease_zahradni_obj,
            self.testova,
            today - timedelta(days=4),
            channel=Channel.EMAIL,
            direction=Direction.IN,
            subject="Zájem o prodloužení smlouvy",
            text="Nájemnice by ráda zůstala ještě rok, ptá se na podmínky.",
            follow_up_date=today + timedelta(days=7),
        )
        note(
            self.lipova,
            self.lease_lipova_obj,
            self.vzorova,
            add_months(today, -8),
            channel=Channel.PHONE,
            direction=Direction.IN,
            subject="Kape baterie v koupelně",
            text="Domluven instalatér na příští týden.",
            follow_up_date=add_months(today, -8) + timedelta(days=5),
            follow_up_done=True,
        )
        note(
            self.vysluni,
            self.lease_vysluni_old,
            self.priklad,
            self.old_end - timedelta(days=60),
            channel=Channel.LETTER,
            direction=Direction.OUT,
            subject="Potvrzení výpovědi",
            text="Potvrzení převzetí výpovědi a termínu předání bytu.",
        )

    def payables(self) -> None:
        start = self.start

        def payable(
            name: str, items: list[tuple[CategoryCode, Property | None, int, str]], **fields: object
        ) -> Payable:
            fields.setdefault("account", self.bank)
            fields.setdefault("valid_from", start)
            return save_payable(
                Payable(name=name, **fields),
                [
                    ItemInput(category_id(code), prop.pk if prop else None, kc(korun), label)
                    for code, prop, korun, label in items
                ],
            )

        manual = payable(
            "SVJ Lipová 12",
            [
                (CategoryCode.HOA_FUND, self.lipova, 1_500, "Fond oprav"),
                (CategoryCode.WATER_COLD, self.lipova, 650, "Voda"),
                (CategoryCode.HEATING, self.lipova, 1_350, "Teplo"),
            ],
            supplier="SVJ Lipová 12",
            method=PaymentMethod.STANDING,
            frequency_months=1,
            due_day=15,
        )
        payable(
            "SVJ Na Výsluní 7",
            [
                (CategoryCode.HOA_FUND, self.vysluni, 1_200, "Fond oprav"),
                (CategoryCode.HEATING, self.vysluni, 1_900, "Teplo"),
                (CategoryCode.WATER_HOT, self.vysluni, 800, "Teplá voda"),
                (CategoryCode.WATER_COLD, self.vysluni, 500, "Studená voda"),
            ],
            supplier="SVJ Na Výsluní 7",
            method=PaymentMethod.SIPO,
            frequency_months=1,
            due_day=12,
            auto=True,
        )
        payable(
            "Elektřina Zahradní 3",
            [(CategoryCode.ELECTRICITY, self.zahradni, 900, "")],
            supplier="Energie Demo, a. s.",
            method=PaymentMethod.DIRECT_DEBIT,
            frequency_months=1,
            due_day=20,
            auto=True,
        )
        payable(
            "Plyn Lipová 12",
            [(CategoryCode.GAS, self.lipova, 700, "")],
            supplier="Plyn Demo, a. s.",
            method=PaymentMethod.DIRECT_DEBIT,
            frequency_months=1,
            due_day=18,
            auto=True,
        )
        payable(
            "Pojištění nemovitostí",
            [
                (CategoryCode.INSURANCE, self.lipova, 2_400, ""),
                (CategoryCode.INSURANCE, self.vysluni, 3_100, ""),
                (CategoryCode.INSURANCE, self.zahradni, 1_900, ""),
                (CategoryCode.INSURANCE, self.garaz, 600, ""),
            ],
            supplier="Pojišťovna Demo",
            method=PaymentMethod.ORDER,
            frequency_months=12,
            due_day=20,
            valid_from=add_months(start, 1),
        )
        tax_year = start.year if start.month <= 5 else start.year + 1
        payable(
            "Daň z nemovitosti",
            [
                (CategoryCode.PROPERTY_TAX, self.lipova, 820, ""),
                (CategoryCode.PROPERTY_TAX, self.vysluni, 1_140, ""),
                (CategoryCode.PROPERTY_TAX, self.zahradni, 610, ""),
                (CategoryCode.PROPERTY_TAX, self.garaz, 240, ""),
            ],
            supplier="Finanční úřad",
            method=PaymentMethod.ORDER,
            frequency_months=12,
            due_day=31,
            valid_from=date(tax_year, 5, 1),
        )
        payable(
            "Vedení účtu",
            [(CategoryCode.OTHER_EXPENSE, None, 49, "Poplatek bance")],
            supplier="Banka Demo",
            method=PaymentMethod.DIRECT_DEBIT,
            frequency_months=1,
            due_day=1,
            auto=True,
        )
        # Automatické se zaplatí samy, ostatní „ručně“ ke splatnosti; poslední splátka
        # SVJ Lipová po splatnosti zůstane nezaplacená (upozornění).
        ensure_dues(self.today)
        dues = list(open_dues(self.today).filter(due_date__lt=self.today).order_by("due_date"))
        unpaid = [d for d in dues if d.payable_id == manual.pk][-1:]
        to_pay = [d.pk for d in dues if d not in unpaid]
        if to_pay:
            pay_dues(to_pay, day=None, today=self.today)

    def household(self) -> None:
        """Výběry zisku do domácnosti čtvrtletně, roční převod na spořicí účet."""
        month = self.start
        while month <= self.today:
            if month.month in (3, 6, 9, 12) and month > self.start:
                day = month.replace(day=25)
                if day <= self.today:
                    self.entry(
                        day,
                        EntryKind.WITHDRAWAL,
                        45_000,
                        "Výběr zisku do domácnosti",
                        account_id=self.bank.pk,
                    )
            if month.month == 1 and month > self.start:
                self.entry(
                    month.replace(day=15),
                    EntryKind.TRANSFER,
                    60_000,
                    "Převod rezervy na spořicí účet",
                    account_id=self.bank.pk,
                    to_account_id=self.savings.pk,
                )
            month = add_months(month, 1)


@transaction.atomic
def generate(today: date) -> DemoSummary:
    """Naplní prázdnou databázi demo daty k danému dni."""
    return _Builder(today).run()
