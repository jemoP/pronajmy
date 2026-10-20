"""Naplní demo databázi smyšlenými daty (ZM-010, P19). Jen při DEMO_MODE a nad databází
s „demo“ v názvu; bez --reset nad neprázdnou databází nic nedělá."""

from datetime import date
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.rentals import demo


class Command(BaseCommand):
    help = "Naplní demo databázi smyšlenými daty; --reset ji nejdřív vymaže i s přílohami."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--reset", action="store_true", help="vymazat všechna data a přílohy a vytvořit znovu"
        )
        parser.add_argument(
            "--today", type=date.fromisoformat, help="den, ke kterému se data vytvoří (RRRR-MM-DD)"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEMO_MODE:
            raise CommandError("seed_demo běží jen v demu (DEMO_MODE=True).")
        if not demo.demo_database_ok():
            raise CommandError("seed_demo běží jen nad databází, která má v názvu „demo“.")
        if options["reset"]:
            demo.reset_database()
            self.stdout.write("Demo databáze a přílohy vymazány.")
        elif demo.has_data():
            self.stdout.write("Demo databáze už obsahuje data, nic se nemění.")
            return
        summary = demo.generate(options["today"] or timezone.localdate())
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo připraveno – byty: {summary.properties}, smlouvy: {summary.leases},"
                f" pohyby: {summary.entries}, přílohy: {summary.attachments}."
                f" Přihlášení {demo.DEMO_USER} / {demo.DEMO_PASSWORD}."
            )
        )
