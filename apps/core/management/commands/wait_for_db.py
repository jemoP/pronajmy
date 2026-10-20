"""Počká, až databáze přijímá spojení – vstupní skript image ho volá před migracemi (ZM-010)."""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Počká na databázi (výchozí nejvýš 60 s)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--timeout", type=int, default=60, help="Nejdelší čekání v sekundách.")

    def handle(self, *args: Any, **options: Any) -> None:
        deadline = time.monotonic() + options["timeout"]
        while True:
            try:
                connection.ensure_connection()
            except OperationalError as error:
                if time.monotonic() >= deadline:
                    raise CommandError(f"Databáze nedostupná: {error}") from error
                time.sleep(2)
            else:
                return
