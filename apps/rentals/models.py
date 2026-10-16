"""Modely pronájmů. Peníze jsou vždy pohyby (money.Entry); pronájmy na ně jen odkazují.
Částky jsou int v haléřích (pole *_cents)."""

from django.db import models

from apps.money.models import Account


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
