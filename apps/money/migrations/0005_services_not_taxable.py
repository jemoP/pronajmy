"""Zálohy na služby, vyúčtování služeb a náklad Služby se nepočítají do daní (ZM-004)."""

from django.db import migrations

NOT_TAXABLE = ["SERVICES", "SETTLEMENT", "UTILITIES"]


def forward(apps, schema_editor):
    apps.get_model("money", "Category").objects.filter(code__in=NOT_TAXABLE).update(taxable=False)


def backward(apps, schema_editor):
    apps.get_model("money", "Category").objects.filter(code__in=NOT_TAXABLE).update(taxable=True)


class Migration(migrations.Migration):
    dependencies = [("money", "0004_category_taxable")]

    operations = [migrations.RunPython(forward, backward)]
