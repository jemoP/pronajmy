"""Kontrola provozního image při buildu: Django najde vše jen ze zkompilovaných .pyc (ZM-010)."""

import os
import sys
from pathlib import Path

# Spouští se jako docker/selftest.pyc – kořen aplikace musí být v cestě.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.core.management import call_command, get_commands
from django.db.migrations.loader import MigrationLoader
from django.template import engines

django.setup()
call_command("check")
apps = {app for app, _ in MigrationLoader(None).disk_migrations}
missing_apps = {"money", "rentals"} - apps
assert not missing_apps, f"Migrace nenalezeny: {missing_apps}"
missing_commands = {"ensure_admin", "wait_for_db"} - set(get_commands())
assert not missing_commands, f"Příkazy nenalezeny: {missing_commands}"
engines["django"].get_template("base.html")
print("Samotest image v pořádku.")
