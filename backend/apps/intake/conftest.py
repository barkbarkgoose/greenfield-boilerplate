"""Shared fixtures for the intake tests: a small, fixed delivery network.

Tests never read the bundled sample data. Every test gets its own
service-area file (three zips) and can ask for the ``network`` fixture:

* 80202 (Denver): north yard 12 mi / 20 min, south yard 20 mi / 35 min
* 80002 (Arvada): west yard only, 4 mi / 10 min
* 80403 (Golden): special request

=====  ==================================  =========================
Yard   Stocks                              Trucks
=====  ==================================  =========================
north  screened_topsoil, fill_dirt         N1 14 yd, N2 6 yd
south  screened_topsoil, compost           S1 12 yd
west   washed_sand                         W1 6 yd
=====  ==================================  =========================
"""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.intake import pricing
from apps.intake.models import Truck, Yard, YardStock

AREA = {
    "version": 1,
    "zips": {
        "80202": {
            "status": "serve",
            "city": "Denver",
            "yards": {"north": {"miles": 12, "minutes": 20}, "south": {"miles": 20, "minutes": 35}},
        },
        "80002": {"status": "serve", "city": "Arvada", "yards": {"west": {"miles": 4, "minutes": 10}}},
        "80403": {"status": "contact", "city": "Golden", "note": "Canyon roads"},
    },
}


@pytest.fixture(autouse=True)
def _intake_setup(settings, tmp_path):
    cache.clear()
    path = tmp_path / "service_area.json"
    path.write_text(json.dumps(AREA))
    settings.SERVICE_AREA_FILE = str(path)
    settings.INTAKE_NOTIFY_EMAILS = ["owner@example.com"]
    settings.SITE_URL = "https://shop.example"
    settings.TURNSTILE_SECRET_KEY = ""
    yield
    cache.clear()


def delivery_day(days: int = 7):
    """The first delivery day at least ``days`` from today."""
    day = timezone.localdate() + timedelta(days=days)
    while not pricing.is_delivery_day(day):
        day += timedelta(days=1)
    return day


@pytest.fixture
def network(db):
    yards = {
        code: Yard.objects.create(code=code, name=f"{code.title()} yard")
        for code in ("north", "south", "west")
    }
    for code, products in {
        "north": ["screened_topsoil", "fill_dirt"],
        "south": ["screened_topsoil", "compost"],
        "west": ["washed_sand"],
    }.items():
        for product in products:
            YardStock.objects.create(yard=yards[code], product=product)
    trucks = {
        "N1": Truck.objects.create(yard=yards["north"], name="N1", capacity_yards=14),
        "N2": Truck.objects.create(yard=yards["north"], name="N2", capacity_yards=6),
        "S1": Truck.objects.create(yard=yards["south"], name="S1", capacity_yards=12),
        "W1": Truck.objects.create(yard=yards["west"], name="W1", capacity_yards=6),
    }
    return SimpleNamespace(yards=yards, trucks=trucks)
