"""Výchozí účely (ZM-002) a rozšíření unaccent (hledání v poznámce bez diakritiky)."""

from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations

# (kód, název, druh, pořadí)
DEFAULT_CATEGORIES = [
    ("RENT", "Nájemné", "INCOME", 10),
    ("SERVICES", "Zálohy na služby", "INCOME", 20),
    ("SETTLEMENT", "Vyúčtování služeb", "INCOME", 30),
    ("OTHER_INCOME", "Ostatní příjmy", "INCOME", 90),
    ("REPAIRS", "Opravy a údržba", "EXPENSE", 110),
    ("INSPECTION", "Revize", "EXPENSE", 120),
    ("INSURANCE", "Pojištění", "EXPENSE", 130),
    ("PROPERTY_TAX", "Daň z nemovitosti", "EXPENSE", 140),
    ("HOA_FUND", "Fond oprav / SVJ", "EXPENSE", 150),
    ("UTILITIES", "Služby", "EXPENSE", 160),
    ("MANAGEMENT", "Správa a inzerce", "EXPENSE", 170),
    ("FEES", "Poplatky", "EXPENSE", 180),
    ("OTHER_EXPENSE", "Ostatní náklady", "EXPENSE", 190),
    ("DEPOSIT", "Jistota", "NEUTRAL", 210),
]


def seed(apps, schema_editor):
    Category = apps.get_model("money", "Category")
    for code, name, kind, sort in DEFAULT_CATEGORIES:
        Category.objects.update_or_create(
            code=code, defaults={"name": name, "kind": kind, "sort": sort}
        )


def unseed(apps, schema_editor):
    Category = apps.get_model("money", "Category")
    Category.objects.filter(code__in=[c[0] for c in DEFAULT_CATEGORIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("money", "0002_entry_links")]

    operations = [
        UnaccentExtension(),
        migrations.RunPython(seed, unseed),
    ]
