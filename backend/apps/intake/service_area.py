"""Where we deliver: the zip-code lookup table.

Rather than modelling geography in the database, every zip code we deliver to
is listed once in a JSON file (``data/service_area.json``, or the
``SERVICE_AREA_FILE`` setting) with its saved distance to each yard:

.. code-block:: json

    {
      "version": 1,
      "zips": {
        "80202": {
          "status": "serve",
          "city": "Denver",
          "yards": {
            "north": {"miles": 8.4, "minutes": 17},
            "south": {"miles": 11.9, "minutes": 22}
          }
        },
        "80403": {"status": "contact", "city": "Golden", "note": "Canyon roads: quoted by hand"}
      }
    }

* ``serve``: normal online ordering; dispatch picks from the listed yards.
  A yard that's missing from a zip's list never delivers there.
* ``contact``: we go there, but by special request only (steep access, long
  haul...). The order form turns into a "contact me" request.
* Not listed at all: outside our area. Customers can still send a special
  request, but no online order.

Distances are one-way miles and drive minutes from the yard. Fill them in by
hand, from a mapping service, or estimate them with
``manage.py build_service_area`` (straight-line distance x a road factor).
Entries marked ``"locked": true`` are never overwritten by that command, so
hand-checked numbers survive a rebuild. ``manage.py check_service_area``
validates the file against the yards in the database.

The file is read once and cached; it's reloaded when it changes on disk.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings

DEFAULT_FILE = Path(__file__).parent / "data" / "service_area.json"
STATUSES = ("serve", "contact")
ZIP_RE = re.compile(r"^\d{5}$")

SERVE = "serve"
CONTACT = "contact"
OUTSIDE = "outside"


@dataclass(frozen=True)
class YardDistance:
    code: str
    miles: Decimal
    minutes: int


@dataclass(frozen=True)
class Area:
    zip_code: str
    status: str  # serve / contact / outside
    city: str = ""
    note: str = ""
    # Nearest (by drive time) first.
    yards: tuple[YardDistance, ...] = field(default_factory=tuple)

    def distance_to(self, yard_code: str) -> YardDistance | None:
        return next((y for y in self.yards if y.code == yard_code), None)


def normalize_zip(value: str | None) -> str:
    """"80202-1234" or " 80202 " -> "80202"; anything else -> ""."""
    digits = re.sub(r"\D", "", (value or "").split("-")[0])
    return digits if ZIP_RE.match(digits) else ""


def path() -> Path:
    return Path(getattr(settings, "SERVICE_AREA_FILE", "") or DEFAULT_FILE)


_cache: dict = {"key": None, "data": None}


def load() -> dict:
    """The parsed file, cached until it changes on disk."""
    file = path()
    try:
        key = (str(file), file.stat().st_mtime_ns)
    except FileNotFoundError:
        return {"version": 1, "zips": {}}
    if _cache["key"] != key:
        with open(file, encoding="utf-8") as handle:
            _cache["data"] = json.load(handle)
        _cache["key"] = key
    return _cache["data"]


def _distances(raw: dict) -> tuple[YardDistance, ...]:
    found = []
    for code, value in (raw or {}).items():
        try:
            found.append(YardDistance(code, Decimal(str(value["miles"])), int(value["minutes"])))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue  # check_service_area reports these
    return tuple(sorted(found, key=lambda d: (d.minutes, d.miles, d.code)))


def lookup(zip_code: str | None) -> Area:
    zip_code = normalize_zip(zip_code)
    entry = load().get("zips", {}).get(zip_code) if zip_code else None
    if not entry or entry.get("status") not in STATUSES:
        return Area(zip_code=zip_code, status=OUTSIDE)
    return Area(
        zip_code=zip_code,
        status=entry["status"],
        city=entry.get("city", ""),
        note=entry.get("note", ""),
        yards=_distances(entry.get("yards")) if entry["status"] == SERVE else (),
    )


def validate(data: dict, yard_codes: set[str] | None = None) -> list[str]:
    """Problems with a service-area file, as readable lines (empty = fine)."""
    problems = []
    zips = data.get("zips")
    if not isinstance(zips, dict):
        return ['Top level needs a "zips" object.']
    for zip_code, entry in sorted(zips.items()):
        where = f"{zip_code}:"
        if not ZIP_RE.match(zip_code):
            problems.append(f"{where} not a 5-digit zip code")
        if not isinstance(entry, dict):
            problems.append(f"{where} entry must be an object")
            continue
        status = entry.get("status")
        if status not in STATUSES:
            problems.append(f'{where} status must be "serve" or "contact" (remove the zip to decline it)')
            continue
        yards = entry.get("yards") or {}
        if status == SERVE and not yards:
            problems.append(f"{where} served but no yards listed")
        for code, value in yards.items():
            if yard_codes is not None and code not in yard_codes:
                problems.append(f"{where} unknown yard {code!r}")
            try:
                miles, minutes = Decimal(str(value["miles"])), int(value["minutes"])
            except (KeyError, TypeError, ValueError, InvalidOperation):
                problems.append(f"{where} yard {code!r} needs numeric miles and minutes")
                continue
            if miles < 0 or minutes <= 0:
                problems.append(f"{where} yard {code!r} has a negative or zero distance")
    return problems
