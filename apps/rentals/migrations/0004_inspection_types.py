"""Výchozí druhy revizí. Intervaly jsou jen návrh – lhůty je potřeba ověřit podle zařízení
a předpisů a v aplikaci upravit."""

from django.db import migrations

TYPES = [
    ("Kontrola a čištění spalinové cesty", 12),
    ("Servis plynového kotle", 12),
    ("Revize plynového zařízení", 36),
    ("Revize elektroinstalace", 60),
    ("Kontrola hasicího přístroje", 12),
    ("Výměna / ověření vodoměrů", 60),
]


def create(apps, schema_editor):
    InspectionType = apps.get_model("rentals", "InspectionType")
    for name, months in TYPES:
        InspectionType.objects.get_or_create(name=name, defaults={"interval_months": months})


def remove(apps, schema_editor):
    InspectionType = apps.get_model("rentals", "InspectionType")
    InspectionType.objects.filter(name__in=[n for n, _ in TYPES], plans__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("rentals", "0003_maintenance_attachments")]

    operations = [migrations.RunPython(create, remove)]
