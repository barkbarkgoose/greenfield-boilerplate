"""Write the parts price table to CSV, in the format import_part_prices reads.

    python manage.py export_part_prices > prices.csv
"""

import csv
import sys

from django.core.management.base import BaseCommand

from apps.intake.models import PartPriceExample

COLUMNS = [
    "service",
    "vehicle_type",
    "vehicle_make",
    "part_brand",
    "description",
    "source",
    "source_url",
    "price",
]


class Command(BaseCommand):
    help = "Export parts price examples as CSV to stdout."

    def handle(self, **options):
        writer = csv.writer(sys.stdout)
        writer.writerow(COLUMNS)
        for example in PartPriceExample.objects.all():
            writer.writerow([getattr(example, column) for column in COLUMNS])
