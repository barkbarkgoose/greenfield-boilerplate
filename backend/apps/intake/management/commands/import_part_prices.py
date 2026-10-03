"""Load parts price examples from a CSV (e.g. exported from your spreadsheet).

    python manage.py import_part_prices prices.csv            # add rows
    python manage.py import_part_prices prices.csv --replace  # CSV becomes the whole table

Columns (header row required): service, vehicle_type, price, and optionally
vehicle_make, part_brand, description, source, source_url. Extra columns (like
the template's "unit" and "notes") are ignored. Rows with no price are skipped,
so a half-filled template imports cleanly.
"""

import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.intake.models import PartPriceExample, VehicleType
from apps.intake.parts import ESTIMATABLE_KEYS

OPTIONAL = ["vehicle_make", "part_brand", "description", "source", "source_url"]


class Command(BaseCommand):
    help = "Import parts price examples from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument(
            "--replace", action="store_true", help="Delete all existing examples first."
        )

    def handle(self, csv_path, replace=False, **options):
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            raise CommandError(f"Can't read {csv_path}: {exc}") from exc

        examples, errors, skipped = [], [], 0
        for line, row in enumerate(rows, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not row.get("price"):
                skipped += 1
                continue
            service = row.get("service", "")
            vehicle_type = row.get("vehicle_type", "").lower()
            if service not in ESTIMATABLE_KEYS:
                errors.append(f"line {line}: unknown service {service!r} (use one of {', '.join(ESTIMATABLE_KEYS)})")
                continue
            if vehicle_type not in VehicleType.values:
                errors.append(f"line {line}: unknown vehicle_type {vehicle_type!r} (use one of {', '.join(VehicleType.values)})")
                continue
            try:
                price = Decimal(row["price"].replace("$", "").replace(",", ""))
            except InvalidOperation:
                errors.append(f"line {line}: price {row['price']!r} isn't a number")
                continue
            if price < 0:
                errors.append(f"line {line}: price can't be negative")
                continue
            examples.append(
                PartPriceExample(
                    service=service,
                    vehicle_type=vehicle_type,
                    price=price,
                    vehicle_make=row.get("vehicle_make", "").upper()[:40],
                    part_brand=row.get("part_brand", "")[:60],
                    description=row.get("description", "")[:120],
                    source=row.get("source", "")[:40],
                    source_url=row.get("source_url", "")[:500],
                )
            )

        if errors:
            raise CommandError("Nothing imported. Fix these rows:\n  " + "\n  ".join(errors))

        with transaction.atomic():
            removed = PartPriceExample.objects.all().delete()[0] if replace else 0
            PartPriceExample.objects.bulk_create(examples)

        summary = f"Imported {len(examples)} price examples"
        if replace:
            summary += f" (replaced {removed})"
        if skipped:
            summary += f"; skipped {skipped} rows with no price"
        self.stdout.write(self.style.SUCCESS(summary + "."))
