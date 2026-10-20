"""Založí účet při prvním startu z PRONAJMY_ADMIN_USER a PRONAJMY_ADMIN_PASSWORD (ZM-010)."""

import os
from typing import Any

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Když v databázi není žádný uživatel, založí správce z proměnných prostředí."

    def handle(self, *args: Any, **options: Any) -> None:
        if User.objects.exists():
            self.stdout.write("Účet už existuje, nic se nemění.")
            return
        username = os.environ.get("PRONAJMY_ADMIN_USER", "").strip()
        password = os.environ.get("PRONAJMY_ADMIN_PASSWORD", "")
        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "Žádný účet: doplň PRONAJMY_ADMIN_USER a PRONAJMY_ADMIN_PASSWORD do .env, "
                    "nebo spusť příkaz createsuperuser."
                )
            )
            return
        User.objects.create_superuser(username, password=password)
        self.stdout.write(self.style.SUCCESS(f"Založen účet {username}."))
