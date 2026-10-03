"""Parts estimates from your own price table.

You record real prices you find (AutoZone, RockAuto, ...) as
``PartPriceExample`` rows: one row per job, vehicle type, and optionally
vehicle make. For a booking, each job is estimated from the examples that best
match the car:

1. same make and same vehicle type   (e.g. TOYOTA sedans)
2. same make, any type               (e.g. any TOYOTA)
3. same vehicle type, any make       (e.g. sedans)

The first group with any examples wins, and the estimate is its min / median /
max. Jobs with no matching examples are left for a manual quote. No external
model is involved: estimates are free, instant to compute, and every number
traces back to a price you entered.

The vehicle type comes from the NHTSA VIN decode (body class, weight class and
make) and staff can correct it per request, which recalculates the estimate.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import threading
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import pricing
from .models import PartPriceExample, ServiceRequest, VehicleType

logger = logging.getLogger(__name__)

# Every service with parts to buy ("other" is quoted by hand).
ESTIMATABLE_KEYS = [s.key for s in pricing.SERVICES if not s.quote_required]

# Makes priced as "european" regardless of body style.
EUROPEAN_MAKES = {
    "ALFA ROMEO", "ASTON MARTIN", "AUDI", "BENTLEY", "BMW", "FIAT", "JAGUAR",
    "LAND ROVER", "MASERATI", "MERCEDES-BENZ", "MINI", "POLESTAR", "PORSCHE",
    "SAAB", "SMART", "VOLKSWAGEN", "VOLVO",
}  # fmt: skip

MAX_EXAMPLES_SHOWN = 8

NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
NHTSA_FIELDS = {
    "ModelYear": "year",
    "Make": "make",
    "Model": "model",
    "Trim": "trim",
    "BodyClass": "body",
    "GVWR": "gvwr",
}

_UNSAFE = re.compile(r"[^A-Za-z0-9 .,/()+:-]")


def _clean_field(value) -> str:
    return _UNSAFE.sub("", str(value or "")).strip()[:60]


# --- Vehicle --------------------------------------------------------------------


def decode_vin(vin: str) -> dict:
    """Best-effort NHTSA vPIC decode. Returns cleaned fields or {}."""
    url = NHTSA_URL.format(vin=urllib.parse.quote(vin))
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            body = json.loads(response.read())
        result = (body.get("Results") or [{}])[0]
    except (urllib.error.URLError, TimeoutError, ValueError, IndexError):
        logger.info("VIN decode failed for parts estimate", exc_info=True)
        return {}
    profile = {}
    for source, target in NHTSA_FIELDS.items():
        value = _clean_field(result.get(source))
        if value and value.lower() not in {"not applicable", "0"}:
            profile[target] = value
    return profile


def vehicle_profile(req: ServiceRequest) -> dict:
    """Decoded vehicle attributes, falling back to what the customer typed."""
    profile = decode_vin(req.vin) if req.vin else {}
    for target, source in (("year", "vehicle_year"), ("make", "vehicle_make"), ("model", "vehicle_model")):
        if not profile.get(target):
            value = _clean_field(getattr(req, source))
            if value:
                profile[target] = value
    if profile.get("make"):
        profile["make"] = profile["make"].upper()
    return profile


def classify(profile: dict) -> str:
    """Best-guess vehicle type, or "" when there isn't enough to go on.

    NHTSA doesn't separate crossovers from SUVs, so SUVs are split by weight:
    GVWR class 1 (up to 6,000 lb) is a crossover, heavier is an SUV.
    """
    if profile.get("make", "").upper() in EUROPEAN_MAKES:
        return VehicleType.EUROPEAN
    body = profile.get("body", "").lower()
    if not body:
        return ""
    if "pickup" in body:
        return VehicleType.TRUCK
    if "sport utility" in body or "multi-purpose" in body or "crossover" in body:
        weight_class = re.search(r"class\s*(\d)", profile.get("gvwr", ""), re.IGNORECASE)
        if weight_class and weight_class.group(1) == "1":
            return VehicleType.CROSSOVER
        return VehicleType.SUV
    if "van" in body:
        return VehicleType.SUV
    return VehicleType.SEDAN


# --- Matching -------------------------------------------------------------------


def jobs_for(services: dict) -> dict[str, int]:
    """Estimatable jobs in catalog order."""
    services = services or {}
    return {key: services[key] for key in ESTIMATABLE_KEYS if services.get(key)}


def matching_examples(service: str, vehicle_type: str, make: str) -> tuple[list[PartPriceExample], str]:
    """The best-matching examples for one job, plus a label for what matched."""
    examples = PartPriceExample.objects.filter(service=service)
    type_label = VehicleType(vehicle_type).label.lower() if vehicle_type else ""
    tiers = []
    if make and vehicle_type:
        tiers.append((examples.filter(vehicle_make=make, vehicle_type=vehicle_type), f"{make.title()} {type_label}"))
    if make:
        tiers.append((examples.filter(vehicle_make=make), make.title()))
    if vehicle_type:
        tiers.append((examples.filter(vehicle_type=vehicle_type), type_label))
    for queryset, label in tiers:
        found = list(queryset)
        if found:
            return found, label
    return [], ""


def _dollars(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"))


def estimate(jobs: dict[str, int], vehicle_type: str, make: str) -> dict:
    services = []
    missing = []
    totals = {"low": Decimal("0"), "typical": Decimal("0"), "high": Decimal("0")}
    for key, qty in jobs.items():
        service = pricing.SERVICES_BY_KEY[key]
        examples, basis = matching_examples(key, vehicle_type, make)
        if not examples:
            missing.append(service.name)
            continue
        prices = [example.price for example in examples]
        line = {
            "low": _dollars(min(prices) * qty),
            "typical": _dollars(Decimal(statistics.median(prices)) * qty),
            "high": _dollars(max(prices) * qty),
        }
        for name in totals:
            totals[name] += line[name]
        services.append(
            {
                "service_key": key,
                "name": service.name,
                "quantity": qty,
                "unit": service.unit or "job",
                **{name: str(amount) for name, amount in line.items()},
                "sample_count": len(examples),
                "basis": basis,
                "examples": [
                    {
                        "part_brand": e.part_brand,
                        "description": e.description,
                        "source": e.source,
                        "price": str(e.price),
                    }
                    for e in sorted(examples, key=lambda e: e.price)[:MAX_EXAMPLES_SHOWN]
                ],
            }
        )
    return {
        "vehicle_type": vehicle_type,
        "vehicle_type_label": VehicleType(vehicle_type).label if vehicle_type else "",
        "services": services,
        "missing": missing,
        **{name: str(amount) for name, amount in totals.items()},
    }


# --- Orchestration --------------------------------------------------------------


def wants_estimate(req: ServiceRequest) -> bool:
    return (
        req.request_type == ServiceRequest.RequestType.BOOKING
        and bool(jobs_for(req.services))
        and PartPriceExample.objects.exists()
    )


def generate_for_request(request_id: int) -> None:
    """(Re)compute a request's parts estimate from the price table."""
    req = ServiceRequest.objects.filter(pk=request_id).first()
    if req is None or not wants_estimate(req):
        return

    profile = vehicle_profile(req)
    if not req.vehicle_type:
        req.vehicle_type = classify(profile)

    result = estimate(jobs_for(req.services), req.vehicle_type, profile.get("make", ""))
    result["vehicle_summary"] = " ".join(
        part for part in (profile.get("year"), profile.get("make", "").title(), profile.get("model")) if part
    )
    result["generated_at"] = timezone.now().isoformat()

    req.parts_estimate_result = result
    req.parts_estimate_status = (
        ServiceRequest.PartsStatus.READY if result["services"] else ServiceRequest.PartsStatus.UNAVAILABLE
    )
    req.save(update_fields=["vehicle_type", "parts_estimate_result", "parts_estimate_status"])


def _run(request_id: int) -> None:
    close_old_connections()
    try:
        generate_for_request(request_id)
    except Exception:  # noqa: BLE001 - a background job must never crash the worker
        logger.exception("Parts estimate failed for request %s", request_id)
        ServiceRequest.objects.filter(
            pk=request_id, parts_estimate_status=ServiceRequest.PartsStatus.PENDING
        ).update(parts_estimate_status=ServiceRequest.PartsStatus.UNAVAILABLE)
    finally:
        close_old_connections()


def schedule(req: ServiceRequest) -> None:
    """Mark a request pending and estimate it off the request thread.

    The table lookup is instant; the thread is only there so the VIN decode
    (a call to NHTSA) never slows down submitting a booking.
    """
    if not wants_estimate(req):
        return
    ServiceRequest.objects.filter(pk=req.pk).update(
        parts_estimate_status=ServiceRequest.PartsStatus.PENDING
    )
    if getattr(settings, "PARTS_ESTIMATE_ASYNC", True):
        threading.Thread(target=_run, args=(req.pk,), daemon=True).start()
    else:
        _run(req.pk)


def as_payload(req: ServiceRequest) -> dict | None:
    """What the API returns about a request's parts estimate."""
    if not req.parts_estimate_status:
        return None
    data = {"status": req.parts_estimate_status}
    if req.parts_estimate_status == ServiceRequest.PartsStatus.READY:
        data.update(req.parts_estimate_result or {})
    return data
