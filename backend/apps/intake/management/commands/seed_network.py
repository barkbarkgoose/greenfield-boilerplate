"""Load the sample yards, trucks and stock (data/sample_network.json).

    python manage.py seed_network

Safe to re-run: yards are matched by code and trucks by name, and existing
rows are updated rather than duplicated. Edit the JSON (or the Django admin)
for your real yards; the yard codes must match data/service_area.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.intake.models import Truck, Yard, YardStock

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample_network.json"


def seed(data: dict) -> dict:
    counts = {"yards": 0, "trucks": 0, "stock": 0}
    with transaction.atomic():
        for row in data["yards"]:
            yard, _ = Yard.objects.update_or_create(
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "address": row.get("address", ""),
                    "latitude": row.get("lat"),
                    "longitude": row.get("lng"),
                    "active": True,
                },
            )
            counts["yards"] += 1
            for product in row.get("products", []):
                YardStock.objects.update_or_create(yard=yard, product=product, defaults={"in_stock": True})
                counts["stock"] += 1
            for truck in row.get("trucks", []):
                Truck.objects.update_or_create(
                    yard=yard,
                    name=truck["name"],
                    defaults={
                        "capacity_yards": truck["capacity_yards"],
                        "workday_minutes": truck.get("workday_minutes", 600),
                        "active": True,
                    },
                )
                counts["trucks"] += 1
    return counts


class Command(BaseCommand):
    help = "Create or update the sample yards, trucks and stock."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(SAMPLE))

    def handle(self, *args, **options):
        counts = seed(json.loads(Path(options["file"]).read_text(encoding="utf-8")))
        self.stdout.write(
            self.style.SUCCESS(f"{counts['yards']} yards, {counts['trucks']} trucks, {counts['stock']} stock rows.")
        )
