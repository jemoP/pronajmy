"""Výchozí služby (ZM-008): zálohy, vyúčtování, Služby a energie."""

from django.db import migrations

SERVICE = [
    "SERVICES",
    "SETTLEMENT",
    "UTILITIES",
    "ELECTRICITY",
    "GAS",
    "WATER_COLD",
    "WATER_HOT",
    "HEATING",
]


def forward(apps, schema_editor):
    apps.get_model("money", "Category").objects.filter(code__in=SERVICE).update(is_service=True)


def backward(apps, schema_editor):
    apps.get_model("money", "Category").objects.filter(code__in=SERVICE).update(is_service=False)


class Migration(migrations.Migration):
    dependencies = [("money", "0009_category_is_service")]

    operations = [migrations.RunPython(forward, backward)]
