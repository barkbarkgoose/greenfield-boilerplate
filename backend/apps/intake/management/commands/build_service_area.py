"""Estimate the zip -> yard distance table from coordinates.

    python manage.py build_service_area zips.csv --out apps/intake/data/service_area.json

``zips.csv`` has one row per zip code you might deliver to:
``zip,lat,lng[,city][,status][,note]`` (a header row is required). Centroids for
every US zip are in the Census "ZCTA Gazetteer" file; trim it to your region.
Leave ``status`` blank to let the distances decide, or set ``contact`` (or
``decline``) to force it, e.g. for mountain zips that are close but slow;
``note`` is shown to staff (and on the order form for special-request zips).

Yard coordinates come from the database (Yard.latitude / longitude) unless
``--yards yards.csv`` (``code,lat,lng``) is given.

Distances are estimates: straight-line miles x ``--road-factor``, and drive
minutes at ``--mph`` plus ``--extra-minutes``. Replace any you know better
(e.g. from Google Maps) by hand and mark the entry ``"locked": true``; a
rebuild with ``--existing`` keeps locked entries as they are.

Rules, by road miles from the *nearest* yard:
* up to ``--serve-miles``: ``serve`` (online ordering)
* up to ``--contact-miles``: ``contact`` (special request)
* farther: left out (declined)
Each served zip lists every yard within ``--yard-max-miles``.
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.intake.models import Yard
from apps.intake.service_area import ZIP_RE

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _read_csv(path: str) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            return [{k.strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(handle)]
    except FileNotFoundError as exc:
        raise CommandError(f"File not found: {path}") from exc


def build(
    zips: list[dict],
    yards: dict[str, tuple[float, float]],
    *,
    road_factor: float = 1.3,
    mph: float = 30.0,
    extra_minutes: int = 5,
    serve_miles: float = 25.0,
    contact_miles: float = 40.0,
    yard_max_miles: float | None = None,
    existing: dict | None = None,
) -> dict:
    """The service-area document for these zips and yards (pure; no I/O)."""
    yard_max_miles = yard_max_miles or contact_miles
    locked = {z: e for z, e in ((existing or {}).get("zips") or {}).items() if e.get("locked")}
    result: dict[str, dict] = {}
    for row in zips:
        zip_code = row.get("zip", "").zfill(5)
        if not ZIP_RE.match(zip_code):
            raise CommandError(f"Bad zip code in CSV: {row.get('zip')!r}")
        if zip_code in locked:
            result[zip_code] = locked[zip_code]
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (KeyError, ValueError) as exc:
            raise CommandError(f"{zip_code}: lat/lng must be numbers") from exc

        distances = {}
        for code, (ylat, ylng) in yards.items():
            miles = haversine_miles(lat, lng, ylat, ylng) * road_factor
            if miles <= yard_max_miles:
                minutes = round(miles / mph * 60) + extra_minutes
                distances[code] = {"miles": float(Decimal(str(miles)).quantize(Decimal("0.1"))), "minutes": minutes}
        nearest = min((d["miles"] for d in distances.values()), default=None)

        forced = row.get("status", "").lower()
        if forced == "decline":
            continue
        if forced == "contact" or (nearest is not None and serve_miles < nearest <= contact_miles):
            status = "contact"
        elif nearest is not None and nearest <= serve_miles and forced in ("", "serve"):
            status = "serve"
        else:
            continue

        entry: dict = {"status": status}
        if row.get("city"):
            entry["city"] = row["city"]
        if row.get("note"):
            entry["note"] = row["note"]
        if status == "serve":
            entry["yards"] = dict(sorted(distances.items(), key=lambda item: item[1]["minutes"]))
        result[zip_code] = entry

    # Locked entries for zips no longer in the CSV are kept too.
    for zip_code, entry in locked.items():
        result.setdefault(zip_code, entry)

    return {
        "version": 1,
        "generated": date.today().isoformat(),
        "method": (
            f"Estimated: straight-line x {road_factor}, {mph:g} mph + {extra_minutes} min. "
            f"Serve <= {serve_miles:g} mi, contact <= {contact_miles:g} mi. Entries with \"locked\": true are hand-checked."
        ),
        "zips": dict(sorted(result.items())),
    }


def dumps(document: dict) -> str:
    """JSON with each yard's distance on one line, so the file stays scannable."""
    text = json.dumps(document, indent=2, ensure_ascii=False)
    return re.sub(
        r'\{\s*"miles": ([\d.]+),\s*"minutes": (\d+)\s*\}',
        r'{"miles": \1, "minutes": \2}',
        text,
    ) + "\n"


class Command(BaseCommand):
    help = "Estimate data/service_area.json from zip centroids and yard coordinates."

    def add_arguments(self, parser):
        parser.add_argument("zips_csv", help="CSV with zip,lat,lng[,city][,status][,note]")
        parser.add_argument("--yards", help="CSV with code,lat,lng (default: yards in the database)")
        parser.add_argument("--existing", help="Current service_area.json; its locked entries are kept")
        parser.add_argument("--out", help="Write here instead of printing")
        parser.add_argument("--road-factor", type=float, default=1.3)
        parser.add_argument("--mph", type=float, default=30.0)
        parser.add_argument("--extra-minutes", type=int, default=5)
        parser.add_argument("--serve-miles", type=float, default=25.0)
        parser.add_argument("--contact-miles", type=float, default=40.0)
        parser.add_argument("--yard-max-miles", type=float, default=None)

    def handle(self, *args, **options):
        if options["yards"]:
            yards = {r["code"]: (float(r["lat"]), float(r["lng"])) for r in _read_csv(options["yards"])}
        else:
            yards = {
                y.code: (float(y.latitude), float(y.longitude))
                for y in Yard.objects.exclude(latitude=None).exclude(longitude=None)
            }
        if not yards:
            raise CommandError("No yard coordinates: set Yard latitude/longitude or pass --yards.")

        existing = None
        if options["existing"] and Path(options["existing"]).exists():
            existing = json.loads(Path(options["existing"]).read_text(encoding="utf-8"))

        document = build(
            _read_csv(options["zips_csv"]),
            yards,
            road_factor=options["road_factor"],
            mph=options["mph"],
            extra_minutes=options["extra_minutes"],
            serve_miles=options["serve_miles"],
            contact_miles=options["contact_miles"],
            yard_max_miles=options["yard_max_miles"],
            existing=existing,
        )
        text = dumps(document)
        if options["out"]:
            Path(options["out"]).write_text(text, encoding="utf-8")
            counts = {"serve": 0, "contact": 0}
            for entry in document["zips"].values():
                counts[entry["status"]] += 1
            self.stdout.write(
                self.style.SUCCESS(f"Wrote {options['out']}: {counts['serve']} served, {counts['contact']} special request.")
            )
        else:
            self.stdout.write(text, ending="")
