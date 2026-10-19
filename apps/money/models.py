"""Peníze pronájmů: účty, účely a pohyby. Částky jsou vždy int v haléřích (pole *_cents).
Názvy tabulek odpovídají datovému modelu v zadání (Meta.db_table)."""

from django.db import models
from django.db.models import F, Q


class AccountKind(models.TextChoices):
    BANK = "BANK", "bankovní účet"
    CASH = "CASH", "hotovost"


class CategoryKind(models.TextChoices):
    INCOME = "INCOME", "příjem"
    EXPENSE = "EXPENSE", "náklad"
    NEUTRAL = "NEUTRAL", "neutrální"


class CategoryCode(models.TextChoices):
    """Interní označení výchozích účelů (ZM-002) – aplikace je najde i po přejmenování."""

    RENT = "RENT", "Nájemné"
    SERVICES = "SERVICES", "Zálohy na služby"
    SETTLEMENT = "SETTLEMENT", "Vyúčtování služeb"
    OTHER_INCOME = "OTHER_INCOME", "Ostatní příjmy"
    REPAIRS = "REPAIRS", "Opravy a údržba"
    INSPECTION = "INSPECTION", "Revize"
    INSURANCE = "INSURANCE", "Pojištění"
    PROPERTY_TAX = "PROPERTY_TAX", "Daň z nemovitosti"
    HOA_FUND = "HOA_FUND", "Fond oprav / SVJ"
    UTILITIES = "UTILITIES", "Služby"
    ELECTRICITY = "ELECTRICITY", "Elektřina"
    GAS = "GAS", "Plyn"
    WATER_COLD = "WATER_COLD", "Studená voda"
    WATER_HOT = "WATER_HOT", "Teplá voda"
    HEATING = "HEATING", "Vytápění"
    MANAGEMENT = "MANAGEMENT", "Správa a inzerce"
    FEES = "FEES", "Poplatky"
    OTHER_EXPENSE = "OTHER_EXPENSE", "Ostatní náklady"
    DEPOSIT = "DEPOSIT", "Jistota"


# Služby a energie pro přehled služeb (ZM-007); „Služby“ = ostatní služby.
SERVICE_CODES = (
    CategoryCode.ELECTRICITY,
    CategoryCode.GAS,
    CategoryCode.WATER_COLD,
    CategoryCode.WATER_HOT,
    CategoryCode.HEATING,
    CategoryCode.UTILITIES,
)

# Účely, u kterých je byt volitelný.
PROPERTY_OPTIONAL = (CategoryCode.OTHER_INCOME, CategoryCode.OTHER_EXPENSE)


class EntryKind(models.TextChoices):
    INCOME = "INCOME", "Příjem"
    EXPENSE = "EXPENSE", "Náklad"
    TRANSFER = "TRANSFER", "Převod"
    WITHDRAWAL = "WITHDRAWAL", "Výběr do domácnosti"
    DEPOSIT = "DEPOSIT", "Vklad z domácnosti"


# Druhy, které peníze na účet přináší / z účtu odnáší (převod odchází z `account`
# a přichází na `to_account`).
INCOMING_KINDS = (EntryKind.INCOME, EntryKind.DEPOSIT)
OUTGOING_KINDS = (EntryKind.EXPENSE, EntryKind.WITHDRAWAL, EntryKind.TRANSFER)
# Druhy s účelem a bytem.
CATEGORIZED_KINDS = (EntryKind.INCOME, EntryKind.EXPENSE)


class Account(models.Model):
    """Účet pronájmů; zůstatek = počáteční stav + příchozí − odchozí pohyby."""

    name = models.CharField("název", max_length=200)
    kind = models.CharField("druh", max_length=10, choices=AccountKind.choices)
    bank_code = models.CharField("kód banky", max_length=10, blank=True)
    account_number = models.CharField("číslo účtu", max_length=50, blank=True)
    opening_balance_cents = models.BigIntegerField("počáteční stav (haléře)", default=0)
    active = models.BooleanField("aktivní", default=True)

    class Meta:
        db_table = "account"
        verbose_name = "účet"
        verbose_name_plural = "účty"
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=AccountKind.values), name="account_kind_valid"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Category(models.Model):
    """Účel pohybu. Neutrální účel (jistota) jde u příjmu i nákladu a nepatří do výsledku."""

    name = models.CharField("název", max_length=100, unique=True)
    kind = models.CharField("druh", max_length=10, choices=CategoryKind.choices)
    code = models.CharField(
        "kód", max_length=20, choices=CategoryCode.choices, unique=True, null=True, blank=True
    )
    sort = models.IntegerField("pořadí", default=0)
    active = models.BooleanField("aktivní", default=True)
    # Průběžné položky (služby přeposílané dodavatelům) do podkladu pro daně nepatří (ZM-004).
    taxable = models.BooleanField("počítat do daní", default=True)
    # Služba (průběžná položka) – výsledek se dělí na nájem a služby (ZM-008).
    is_service = models.BooleanField("služba (průběžná položka)", default=False)

    class Meta:
        db_table = "category"
        verbose_name = "účel"
        verbose_name_plural = "účely"
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=CategoryKind.values), name="category_kind_valid"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Entry(models.Model):
    """Pohyb peněz. Částka je vždy kladná, směr určuje druh."""

    date = models.DateField("datum", db_index=True)
    kind = models.CharField("druh", max_length=10, choices=EntryKind.choices)
    amount_cents = models.BigIntegerField("částka (haléře)")
    account = models.ForeignKey(
        Account, models.PROTECT, related_name="entries", verbose_name="účet"
    )
    to_account = models.ForeignKey(
        Account,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_transfers",
        verbose_name="na účet",
    )
    category = models.ForeignKey(
        Category, models.PROTECT, null=True, blank=True, verbose_name="účel"
    )
    property = models.ForeignKey(
        "rentals.Property",
        models.PROTECT,
        null=True,
        blank=True,
        related_name="entries",
        verbose_name="byt",
    )
    note = models.TextField("poznámka", blank=True)
    # Náklad vzniklý ze splátky předpisu platby (ZM-006); smazání nákladu splátku znovu otevře.
    payable_due = models.ForeignKey(
        "PayableDue", models.SET_NULL, null=True, blank=True, related_name="entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "entry"
        verbose_name = "pohyb"
        verbose_name_plural = "pohyby"
        constraints = [
            models.CheckConstraint(condition=Q(amount_cents__gt=0), name="entry_amount_positive"),
            models.CheckConstraint(condition=Q(kind__in=EntryKind.values), name="entry_kind_valid"),
            # Cílový účet má jen převod, a to jiný než zdrojový.
            models.CheckConstraint(
                condition=(
                    Q(kind=EntryKind.TRANSFER)
                    & Q(to_account__isnull=False)
                    & ~Q(to_account=F("account"))
                )
                | (~Q(kind=EntryKind.TRANSFER) & Q(to_account__isnull=True)),
                name="entry_transfer_accounts",
            ),
            # Účel a byt mají jen příjem a náklad.
            models.CheckConstraint(
                condition=Q(kind__in=CATEGORIZED_KINDS)
                | (Q(category__isnull=True) & Q(property__isnull=True)),
                name="entry_category_only_income_expense",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.get_kind_display()} {self.amount_cents}"


class PaymentMethod(models.TextChoices):
    ORDER = "ORDER", "příkaz"
    STANDING = "STANDING", "trvalý příkaz"
    DIRECT_DEBIT = "DIRECT_DEBIT", "inkaso"
    SIPO = "SIPO", "SIPO"
    CASH = "CASH", "hotově"


class Frequency(models.IntegerChoices):
    MONTHLY = 1, "měsíčně"
    QUARTERLY = 3, "čtvrtletně"
    HALF_YEARLY = 6, "pololetně"
    YEARLY = 12, "ročně"


class Payable(models.Model):
    """Předpis platby dodavateli s platností v čase (ZM-006)."""

    name = models.CharField("název", max_length=200)
    supplier = models.CharField("dodavatel", max_length=200, blank=True)
    supplier_account = models.CharField("číslo účtu dodavatele", max_length=50, blank=True)
    bank_code = models.CharField("kód banky", max_length=10, blank=True)
    variable_symbol = models.CharField("variabilní symbol", max_length=10, blank=True)
    specific_symbol = models.CharField(
        "specifický symbol / spojovací číslo", max_length=20, blank=True
    )
    method = models.CharField(
        "způsob platby", max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.ORDER
    )
    account = models.ForeignKey(
        Account, models.PROTECT, related_name="payables", verbose_name="z účtu"
    )
    frequency_months = models.PositiveSmallIntegerField(
        "četnost", choices=Frequency.choices, default=Frequency.MONTHLY
    )
    due_day = models.PositiveSmallIntegerField("den splatnosti", default=15)
    valid_from = models.DateField("platí od")
    valid_to = models.DateField("platí do", null=True, blank=True)  # NULL = neurčitě
    # Výchozí je zápis k potvrzení; automaticky jen tam, kde peníze odchází samy.
    auto = models.BooleanField("zapisovat automaticky k datu splatnosti", default=False)
    previous = models.ForeignKey(
        "self", models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="navazuje na"
    )
    note = models.TextField("poznámka", blank=True)

    class Meta:
        db_table = "payable"
        verbose_name = "předpis platby"
        verbose_name_plural = "předpisy plateb"
        constraints = [
            models.CheckConstraint(
                condition=Q(due_day__gte=1, due_day__lte=31), name="payable_due_day_valid"
            ),
            models.CheckConstraint(
                condition=Q(frequency_months__in=Frequency.values), name="payable_frequency_valid"
            ),
            models.CheckConstraint(
                condition=Q(method__in=PaymentMethod.values), name="payable_method_valid"
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="payable_valid_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class PayableItem(models.Model):
    """Řádek rozpisu platby: účel (náklad), byt a částka."""

    payable = models.ForeignKey(Payable, models.CASCADE, related_name="items")
    category = models.ForeignKey(Category, models.PROTECT, related_name="+", verbose_name="účel")
    property = models.ForeignKey(
        "rentals.Property",
        models.PROTECT,
        null=True,
        blank=True,
        related_name="payable_items",
        verbose_name="byt",
    )
    amount_cents = models.BigIntegerField("částka (haléře)")
    label = models.CharField("popis", max_length=100, blank=True)

    class Meta:
        db_table = "payable_item"
        verbose_name = "řádek předpisu platby"
        verbose_name_plural = "řádky předpisu platby"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_cents__gt=0), name="payable_item_amount_positive"
            )
        ]

    def __str__(self) -> str:
        return self.label or str(self.category)


class PayableDue(models.Model):
    """Splátka předpisu platby; zaplacená = vznikl z ní aspoň jeden náklad."""

    payable = models.ForeignKey(Payable, models.CASCADE, related_name="dues")
    period = models.DateField("období")  # 1. den měsíce
    due_date = models.DateField("splatnost")
    # Jednorázově upravená částka (jen u předpisu s jedním řádkem); NULL = podle rozpisu.
    amount_cents = models.BigIntegerField("upravená částka (haléře)", null=True, blank=True)
    skipped = models.BooleanField("přeskočeno", default=False)

    class Meta:
        db_table = "payable_due"
        verbose_name = "splátka"
        verbose_name_plural = "splátky"
        constraints = [
            models.UniqueConstraint(fields=["payable", "period"], name="payable_due_unique"),
            models.CheckConstraint(
                condition=Q(amount_cents__isnull=True) | Q(amount_cents__gt=0),
                name="payable_due_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.payable} {self.period.month}/{self.period.year}"
