"""Výchozí účely energií (ZM-007): náklady mimo daně, řazené za Služby. Existující účel
stejného názvu (bez kódu) jen dostane kód, aby nevznikla duplicita."""

from django.db import migrations

ENERGY = [
    ("ELECTRICITY", "Elektřina", 161),
    ("GAS", "Plyn", 162),
    ("WATER_COLD", "Studená voda", 163),
    ("WATER_HOT", "Teplá voda", 164),
    ("HEATING", "Vytápění", 165),
]


def forward(apps, schema_editor):
    Category = apps.get_model("money", "Category")
    for code, name, sort in ENERGY:
        if Category.objects.filter(code=code).exists():
            continue
        existing = Category.objects.filter(name__iexact=name, code__isnull=True).first()
        if existing is not None and existing.kind == "EXPENSE":
            existing.code = code
            existing.save(update_fields=["code"])
            continue
        Category.objects.create(code=code, name=name, kind="EXPENSE", sort=sort, taxable=False)


def backward(apps, schema_editor):
    Category = apps.get_model("money", "Category")
    Category.objects.filter(code__in=[c for c, _, _ in ENERGY], entry__isnull=True).delete()
    Category.objects.filter(code__in=[c for c, _, _ in ENERGY]).update(code=None)


class Migration(migrations.Migration):
    dependencies = [("money", "0007_category_energy_codes")]

    operations = [migrations.RunPython(forward, backward)]
