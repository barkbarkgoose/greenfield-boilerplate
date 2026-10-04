"""Validate the service-area file against the yards in the database.

    python manage.py check_service_area [path/to/service_area.json]

Exits non-zero when there's a problem, so it can run in CI or before deploys.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.intake import service_area
from apps.intake.models import Yard


class Command(BaseCommand):
    help = "Check data/service_area.json for mistakes and unknown yards."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", help="Defaults to the SERVICE_AREA_FILE in use")
        parser.add_argument("--no-db", action="store_true", help="Skip checking yard codes against the database")

    def handle(self, *args, **options):
        path = Path(options["path"]) if options["path"] else service_area.path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CommandError(f"Not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} isn't valid JSON: {exc}") from exc

        codes = None if options["no_db"] else set(Yard.objects.values_list("code", flat=True))
        problems = service_area.validate(data, codes)
        zips = data.get("zips") or {}
        if problems:
            for problem in problems:
                self.stderr.write(f"  {problem}")
            raise CommandError(f"{len(problems)} problem(s) in {path}")

        served = sum(1 for e in zips.values() if e.get("status") == "serve")
        self.stdout.write(
            self.style.SUCCESS(f"{path}: OK. {served} served, {len(zips) - served} special request.")
        )
        if codes is not None:
            used = {code for e in zips.values() for code in (e.get("yards") or {})}
            for code in sorted(codes - used):
                self.stdout.write(self.style.WARNING(f"  Yard {code!r} isn't listed for any zip, so it never delivers."))
