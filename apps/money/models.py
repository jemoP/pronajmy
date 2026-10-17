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
    MANAGEMENT = "MANAGEMENT", "Správa a inzerce"
    FEES = "FEES", "Poplatky"
    OTHER_EXPENSE = "OTHER_EXPENSE", "Ostatní náklady"
    DEPOSIT = "DEPOSIT", "Jistota"


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
