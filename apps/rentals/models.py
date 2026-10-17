"""Modely pronájmů. Peníze jsou vždy pohyby (money.Entry); pronájmy na ně jen odkazují.
Částky jsou int v haléřích (pole *_cents)."""

import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from django.db import models
from django.db.models import Q

from apps.core.formatting import format_date
from apps.money.models import Account, Entry


class Property(models.Model):
    """Pronajímaný byt nebo jiná jednotka."""

    name = models.CharField("název", max_length=200, unique=True)
    address = models.CharField("adresa", max_length=300, blank=True)
    unit = models.CharField("číslo jednotky", max_length=50, blank=True)
    layout = models.CharField("dispozice", max_length=20, blank=True)
    # Plocha v m² – nejde o částku, proto Decimal.
    floor_area = models.DecimalField(
        "plocha (m²)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    # Účet, na který chodí nájem (výchozí pro zápis platby).
    account = models.ForeignKey(
        Account, models.PROTECT, null=True, blank=True, related_name="+", verbose_name="účet"
    )
    active = models.BooleanField("aktivní", default=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        db_table = "property"
        verbose_name = "byt"
        verbose_name_plural = "byty"

    def __str__(self) -> str:
        return self.name


class Tenant(models.Model):
    """Nájemník. Rodné číslo ani číslo dokladu se neukládají."""

    name = models.CharField("jméno", max_length=200)
    phone = models.CharField("telefon", max_length=50, blank=True)
    email = models.EmailField("e-mail", blank=True)
    address = models.CharField("adresa", max_length=300, blank=True)
    birth_date = models.DateField("datum narození", null=True, blank=True)
    active = models.BooleanField("aktivní", default=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        db_table = "tenant"
        verbose_name = "nájemník"
        verbose_name_plural = "nájemníci"

    def __str__(self) -> str:
        return self.name


class LeaseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Návrh"
    ACTIVE = "ACTIVE", "Platná"
    ENDED = "ENDED", "Ukončená"


class Lease(models.Model):
    """Nájemní smlouva; podmínky platné k datu = smlouva + účinné dodatky."""

    property = models.ForeignKey(
        Property, models.PROTECT, related_name="leases", verbose_name="byt"
    )
    number = models.CharField("číslo smlouvy", max_length=50, blank=True)
    signed_date = models.DateField("podepsána", null=True, blank=True)
    start_date = models.DateField("nájem od")
    end_date = models.DateField("nájem do", null=True, blank=True)  # NULL = doba neurčitá
    rent_cents = models.BigIntegerField("nájem (haléře)")
    services_cents = models.BigIntegerField("zálohy na služby (haléře)", default=0)
    due_day = models.PositiveSmallIntegerField("den splatnosti", default=5)
    deposit_cents = models.BigIntegerField("jistota (haléře)", default=0)
    variable_symbol = models.CharField("variabilní symbol", max_length=10, blank=True)
    account = models.ForeignKey(
        Account, models.PROTECT, null=True, blank=True, related_name="+", verbose_name="účet"
    )
    status = models.CharField(
        "stav", max_length=10, choices=LeaseStatus.choices, default=LeaseStatus.ACTIVE
    )
    # Od kdy se tvoří předpisy a sleduje saldo; NULL = od začátku nájmu.
    charges_from = models.DateField("sledovat saldo od", null=True, blank=True)
    terminated_on = models.DateField("ukončena ke dni", null=True, blank=True)
    termination_reason = models.CharField("důvod ukončení", max_length=300, blank=True)
    note = models.TextField("poznámka", blank=True)
    tenants = models.ManyToManyField(Tenant, through="LeaseTenant", related_name="leases")

    class Meta:
        db_table = "lease"
        verbose_name = "nájemní smlouva"
        verbose_name_plural = "nájemní smlouvy"
        constraints = [
            models.CheckConstraint(
                condition=Q(rent_cents__gte=0, services_cents__gte=0, deposit_cents__gte=0),
                name="lease_amounts_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(due_day__gte=1, due_day__lte=31), name="lease_due_day_valid"
            ),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")),
                name="lease_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(status__in=LeaseStatus.values), name="lease_status_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.property} od {format_date(self.start_date)}"


class TenantRole(models.TextChoices):
    MAIN = "MAIN", "nájemce"
    CO_TENANT = "CO_TENANT", "spolunájemce"


class LeaseTenant(models.Model):
    lease = models.ForeignKey(Lease, models.CASCADE, related_name="lease_tenants")
    tenant = models.ForeignKey(Tenant, models.PROTECT, related_name="lease_tenants")
    role = models.CharField("role", max_length=10, choices=TenantRole.choices)

    class Meta:
        db_table = "lease_tenant"
        verbose_name = "nájemník smlouvy"
        verbose_name_plural = "nájemníci smlouvy"
        constraints = [
            models.UniqueConstraint(fields=["lease", "tenant"], name="lease_tenant_unique")
        ]

    def __str__(self) -> str:
        return f"{self.tenant} ({self.get_role_display()})"


class LeaseAmendment(models.Model):
    """Dodatek mění nájem, zálohy nebo konec smlouvy od data účinnosti (NULL = beze změny)."""

    lease = models.ForeignKey(Lease, models.CASCADE, related_name="amendments")
    number = models.CharField("číslo dodatku", max_length=50, blank=True)
    signed_date = models.DateField("podepsán", null=True, blank=True)
    effective_date = models.DateField("účinný od")
    description = models.TextField("popis", blank=True)
    rent_cents = models.BigIntegerField("nový nájem (haléře)", null=True, blank=True)
    services_cents = models.BigIntegerField("nové zálohy (haléře)", null=True, blank=True)
    end_date = models.DateField("nový konec nájmu", null=True, blank=True)

    class Meta:
        db_table = "lease_amendment"
        verbose_name = "dodatek"
        verbose_name_plural = "dodatky"
        constraints = [
            models.CheckConstraint(
                condition=(Q(rent_cents__isnull=True) | Q(rent_cents__gte=0))
                & (Q(services_cents__isnull=True) | Q(services_cents__gte=0)),
                name="lease_amendment_amounts_not_negative",
            )
        ]

    def __str__(self) -> str:
        return f"Dodatek {self.number or self.pk} od {format_date(self.effective_date)}"


class ChargeKind(models.TextChoices):
    RENT = "RENT", "Nájem"
    SERVICES = "SERVICES", "Zálohy na služby"
    SETTLEMENT = "SETTLEMENT", "Vyúčtování"
    DEPOSIT = "DEPOSIT", "Jistota"
    OTHER = "OTHER", "Ostatní"


MONTHLY_KINDS = (ChargeKind.RENT, ChargeKind.SERVICES)


class RentCharge(models.Model):
    """Předpis. Částka má znaménko: záporná = přeplatek nebo sleva (dobropis)."""

    lease = models.ForeignKey(Lease, models.CASCADE, related_name="charges")
    kind = models.CharField("druh", max_length=10, choices=ChargeKind.choices)
    period = models.DateField("měsíc", null=True, blank=True)  # 1. den měsíce
    due_date = models.DateField("splatnost")
    amount_cents = models.BigIntegerField("částka (haléře)")
    # Ručně upravený předpis se při doplňování znovu negeneruje.
    manual = models.BooleanField("ručně", default=False)
    note = models.CharField("poznámka", max_length=300, blank=True)

    class Meta:
        db_table = "rent_charge"
        verbose_name = "předpis"
        verbose_name_plural = "předpisy"
        constraints = [
            models.UniqueConstraint(
                fields=["lease", "kind", "period"],
                condition=Q(kind__in=MONTHLY_KINDS),
                name="rent_charge_monthly_unique",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=MONTHLY_KINDS) | Q(period__isnull=False),
                name="rent_charge_monthly_has_period",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=ChargeKind.values), name="rent_charge_kind_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {format_date(self.due_date)}"


class PaymentKind(models.TextChoices):
    PAYMENT = "PAYMENT", "Platba"
    DEPOSIT = "DEPOSIT", "Přijatá jistota"
    REFUND = "REFUND", "Vrácený přeplatek"
    DEPOSIT_RETURN = "DEPOSIT_RETURN", "Vrácená jistota"
    DEPOSIT_OFFSET = "DEPOSIT_OFFSET", "Započtení jistoty"


class RentPayment(models.Model):
    """Vazba pohybu na smlouvu. Jeden pohyb jde rozdělit (první nájem + jistota);
    započtení jistoty na dluh pohyb nemá a nese vlastní datum."""

    lease = models.ForeignKey(Lease, models.CASCADE, related_name="payments")
    # Smazání pohybu vazbu odstraní.
    entry = models.ForeignKey(
        Entry, models.CASCADE, null=True, blank=True, related_name="rent_payments"
    )
    # Platba konkrétního předpisu (ZM-005) – kryje nejdřív jeho; bez vazby jde do FIFO.
    charge = models.ForeignKey(
        RentCharge, models.SET_NULL, null=True, blank=True, related_name="payments"
    )
    kind = models.CharField("druh", max_length=15, choices=PaymentKind.choices)
    amount_cents = models.BigIntegerField("částka (haléře)")
    date = models.DateField("datum", null=True, blank=True)
    note = models.CharField("poznámka", max_length=300, blank=True)

    class Meta:
        db_table = "rent_payment"
        verbose_name = "platba nájmu"
        verbose_name_plural = "platby nájmu"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0), name="rent_payment_amount_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind=PaymentKind.DEPOSIT_OFFSET, entry__isnull=True, date__isnull=False)
                    | (~Q(kind=PaymentKind.DEPOSIT_OFFSET) & Q(entry__isnull=False))
                ),
                name="rent_payment_entry_by_kind",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=PaymentKind.values), name="rent_payment_kind_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.amount_cents}"

    @property
    def paid_on(self) -> datetime.date | None:
        return self.entry.date if self.entry else self.date


class Channel(models.TextChoices):
    PHONE = "PHONE", "telefon"
    EMAIL = "EMAIL", "e-mail"
    SMS = "SMS", "SMS"
    IN_PERSON = "IN_PERSON", "osobně"
    LETTER = "LETTER", "dopis"
    OTHER = "OTHER", "jinak"


class Direction(models.TextChoices):
    IN = "IN", "příchozí"
    OUT = "OUT", "odchozí"


class Communication(models.Model):
    """Záznam komunikace s nájemníkem; volitelný termín vyřízení."""

    property = models.ForeignKey(
        Property,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="communications",
        verbose_name="byt",
    )
    lease = models.ForeignKey(
        Lease,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="communications",
        verbose_name="smlouva",
    )
    tenant = models.ForeignKey(
        Tenant,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="communications",
        verbose_name="nájemník",
    )
    occurred_at = models.DateTimeField("kdy")
    channel = models.CharField("kanál", max_length=10, choices=Channel.choices)
    direction = models.CharField("směr", max_length=3, choices=Direction.choices)
    subject = models.CharField("předmět", max_length=200)
    text = models.TextField("text", blank=True)
    follow_up_date = models.DateField("vyřídit do", null=True, blank=True)
    follow_up_done = models.BooleanField("vyřízeno", default=False)

    class Meta:
        db_table = "communication"
        verbose_name = "komunikace"
        verbose_name_plural = "komunikace"
        constraints = [
            models.CheckConstraint(
                condition=Q(property__isnull=False)
                | Q(lease__isnull=False)
                | Q(tenant__isnull=False),
                name="communication_has_subject",
            )
        ]

    def __str__(self) -> str:
        return self.subject


class RepairStatus(models.TextChoices):
    REPORTED = "REPORTED", "Nahlášeno"
    ORDERED = "ORDERED", "Objednáno"
    DONE = "DONE", "Hotovo"
    CANCELLED = "CANCELLED", "Zrušeno"


OPEN_REPAIR = (RepairStatus.REPORTED, RepairStatus.ORDERED)


class PaidBy(models.TextChoices):
    OWNER = "OWNER", "pronajímatel"
    TENANT = "TENANT", "nájemce"
    INSURANCE = "INSURANCE", "pojišťovna"


class Repair(models.Model):
    """Oprava / závada; náklad pronajímatele je pohyb, oprava na něj jen odkazuje."""

    property = models.ForeignKey(
        Property, models.PROTECT, related_name="repairs", verbose_name="byt"
    )
    lease = models.ForeignKey(
        Lease,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="repairs",
        verbose_name="smlouva",
    )
    reported_date = models.DateField("nahlášeno")
    reported_by = models.CharField("nahlásil", max_length=200, blank=True)
    title = models.CharField("závada / oprava", max_length=200)
    description = models.TextField("popis", blank=True)
    status = models.CharField(
        "stav", max_length=10, choices=RepairStatus.choices, default=RepairStatus.REPORTED
    )
    contractor = models.CharField("dodavatel", max_length=200, blank=True)
    done_date = models.DateField("hotovo dne", null=True, blank=True)
    cost_cents = models.BigIntegerField("náklady (haléře)", null=True, blank=True)
    paid_by = models.CharField("platí", max_length=10, choices=PaidBy.choices, default=PaidBy.OWNER)
    entry = models.ForeignKey(Entry, models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "repair"
        verbose_name = "oprava"
        verbose_name_plural = "opravy"
        constraints = [
            models.CheckConstraint(
                condition=Q(cost_cents__isnull=True) | Q(cost_cents__gte=0),
                name="repair_cost_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(status__in=RepairStatus.values), name="repair_status_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.title


class InspectionType(models.Model):
    """Druh pravidelné revize; výchozí intervaly jsou jen návrh."""

    name = models.CharField("název", max_length=200, unique=True)
    interval_months = models.PositiveSmallIntegerField("interval (měsíce)")
    remind_days = models.PositiveSmallIntegerField("upozornit dní předem", default=30)
    active = models.BooleanField("aktivní", default=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        db_table = "inspection_type"
        verbose_name = "druh revize"
        verbose_name_plural = "druhy revizí"
        constraints = [
            models.CheckConstraint(
                condition=Q(interval_months__gte=1), name="inspection_type_interval_positive"
            )
        ]

    def __str__(self) -> str:
        return self.name


class InspectionPlan(models.Model):
    """Co a jak často se v bytě kontroluje."""

    property = models.ForeignKey(
        Property, models.PROTECT, related_name="inspection_plans", verbose_name="byt"
    )
    type = models.ForeignKey(
        InspectionType, models.PROTECT, related_name="plans", verbose_name="druh revize"
    )
    device = models.CharField("zařízení", max_length=200, blank=True)
    # NULL = interval podle druhu revize.
    interval_months = models.PositiveSmallIntegerField("interval (měsíce)", null=True, blank=True)
    first_due_date = models.DateField("první termín", null=True, blank=True)
    active = models.BooleanField("aktivní", default=True)
    note = models.TextField("poznámka", blank=True)

    class Meta:
        db_table = "inspection_plan"
        verbose_name = "plán revize"
        verbose_name_plural = "plány revizí"
        constraints = [
            models.CheckConstraint(
                condition=Q(interval_months__isnull=True) | Q(interval_months__gte=1),
                name="inspection_plan_interval_positive",
            )
        ]

    def __str__(self) -> str:
        return f"{self.type} – {self.device}" if self.device else str(self.type)


class InspectionResult(models.TextChoices):
    OK = "OK", "bez závad"
    DEFECTS = "DEFECTS", "se závadami"
    FAILED = "FAILED", "nevyhovuje"


class Inspection(models.Model):
    """Provedená revize; next_due_date = datum provedení + interval (jde změnit)."""

    plan = models.ForeignKey(InspectionPlan, models.PROTECT, related_name="inspections")
    done_date = models.DateField("provedeno")
    next_due_date = models.DateField("příští termín", null=True, blank=True)
    result = models.CharField("výsledek", max_length=10, choices=InspectionResult.choices)
    contractor = models.CharField("firma / technik", max_length=200, blank=True)
    cost_cents = models.BigIntegerField("náklady (haléře)", null=True, blank=True)
    entry = models.ForeignKey(Entry, models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.TextField("poznámka", blank=True)

    class Meta:
        db_table = "inspection"
        verbose_name = "revize"
        verbose_name_plural = "revize"
        constraints = [
            models.CheckConstraint(
                condition=Q(cost_cents__isnull=True) | Q(cost_cents__gte=0),
                name="inspection_cost_not_negative",
            )
        ]

    def __str__(self) -> str:
        return f"{self.plan} {format_date(self.done_date)}"


def with_attachment_count[M: models.Model](qs: models.QuerySet[M]) -> models.QuerySet[M]:
    """Počet příloh záznamu (attachment_count) pro příznak v seznamech."""
    annotated = qs.annotate(attachment_count=models.Count("attachments", distinct=True))
    return cast("models.QuerySet[M]", annotated)


def attachment_path(instance: "Attachment", filename: str) -> str:
    """Soubor pod náhodným jménem – původní název je jen v databázi."""
    return f"rentals/{uuid4().hex}{Path(filename).suffix.lower()}"


ATTACHMENT_OWNERS = ("lease", "amendment", "communication", "repair", "inspection")


def _exactly_one(fields: tuple[str, ...]) -> Q:
    result = Q()
    for owner in fields:
        case = Q(**{f"{owner}__isnull": False})
        for other in fields:
            if other != owner:
                case &= Q(**{f"{other}__isnull": True})
        result |= case
    return result


class Attachment(models.Model):
    """Příloha (sken smlouvy, protokol, foto) k právě jednomu záznamu."""

    lease = models.ForeignKey(
        Lease, models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    amendment = models.ForeignKey(
        LeaseAmendment, models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    communication = models.ForeignKey(
        Communication, models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    repair = models.ForeignKey(
        Repair, models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    inspection = models.ForeignKey(
        Inspection, models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    file = models.FileField("soubor", upload_to=attachment_path)
    original_name = models.CharField("název souboru", max_length=255)
    content_type = models.CharField("typ", max_length=100)
    size = models.PositiveIntegerField("velikost (B)")
    uploaded_at = models.DateTimeField("nahráno", auto_now_add=True)

    class Meta:
        db_table = "attachment"
        verbose_name = "příloha"
        verbose_name_plural = "přílohy"
        constraints = [
            models.CheckConstraint(
                condition=_exactly_one(ATTACHMENT_OWNERS), name="attachment_one_owner"
            )
        ]

    def __str__(self) -> str:
        return self.original_name
