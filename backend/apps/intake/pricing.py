"""Service catalog and pricing rules for the mobile mechanic intake form.

This module is the single source of truth for prices. The frontend reads the
catalog from `/api/v1/intake/catalog/` and asks `/api/v1/intake/estimate/` for
live quotes, and the request endpoint re-prices every submission here, so a
price change only ever needs to happen in this file.

How prices are built
--------------------
* Every job is priced from its book labor hours at ``LABOR_RATE``, which is the
  take-home target (``TARGET_HOURLY_RATE``) plus a per-hour insurance reserve.
* Driving is never billed against labor hours. Each visit carries one
  ``SERVICE_CALL_FEE`` that pays round-trip drive time at the target rate plus
  fuel/vehicle wear, so wrench time still nets the target rate.
* Brakes, rotors and suspension share the same teardown (wheel off, caliper
  off), so doing them together saves real hours. Those saved hours come off
  the bill as a bundle discount.
* Small add-ons (oil change, air filter) are free when the rest of the visit
  is already a long job, since the car is up and the tools are out.
* Big jobs get a volume rate: once labor passes ``VOLUME_THRESHOLD``, every
  further hour bills at ``VOLUME_RATE`` instead of ``LABOR_RATE``.
* Prices round *up* to the nearest $5 and discounts round *down*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .i18n import t

# --- Business inputs (edit these) ------------------------------------------

TARGET_HOURLY_RATE = Decimal("50.00")
INSURANCE_PER_LABOR_HOUR = Decimal("5.00")
TRAVEL_HOURS_PER_VISIT = Decimal("0.75")
VEHICLE_COST_PER_VISIT = Decimal("7.50")

BOOKING_LEAD_DAYS = 14
"""Standard lead time so parts can be ordered at normal prices."""

EMERGENCY_WINDOW_DAYS = 7
"""Jobs requested within this many days of today are same-week emergencies."""

EMERGENCY_FEE = Decimal("75.00")

FREE_ADDON_KEYS = ("oil_change", "air_filter")
"""Add-ons thrown in free once the rest of the visit is long enough."""

FREE_ADDON_MIN_HOURS = Decimal("2")
"""Labor hours the *other* work must reach before the add-ons are free."""

VOLUME_THRESHOLD = Decimal("200.00")
"""Labor revenue (after bundles, before fees) at which the volume rate starts."""

VOLUME_RATE = Decimal("25.00")
"""Hourly rate for labor past ``VOLUME_THRESHOLD``."""

# --- Derived rates ----------------------------------------------------------

_FIVE = Decimal("5")


def round_up_5(amount: Decimal) -> Decimal:
    return ((amount / _FIVE).to_integral_value(rounding=ROUND_CEILING) * _FIVE).quantize(
        Decimal("0.01")
    )


def round_down_5(amount: Decimal) -> Decimal:
    return ((amount / _FIVE).to_integral_value(rounding=ROUND_FLOOR) * _FIVE).quantize(
        Decimal("0.01")
    )


LABOR_RATE = TARGET_HOURLY_RATE + INSURANCE_PER_LABOR_HOUR
SERVICE_CALL_FEE = round_up_5(
    TRAVEL_HOURS_PER_VISIT * TARGET_HOURLY_RATE + VEHICLE_COST_PER_VISIT
)


@dataclass(frozen=True)
class Service:
    key: str
    labor_hours: Decimal
    unit: str | None = None
    max_quantity: int = 1
    quote_required: bool = False

    # Labels come from the text map in the active language (see i18n.py).
    @property
    def name(self) -> str:
        return t(f"service__name--{self.key}")

    @property
    def description(self) -> str:
        return t(f"service__description--{self.key}")

    @property
    def price(self) -> Decimal:
        if self.quote_required:
            return Decimal("0.00")
        return round_up_5(self.labor_hours * LABOR_RATE)


@dataclass(frozen=True)
class Bundle:
    key: str
    hours_saved_per_unit: Decimal

    @property
    def name(self) -> str:
        return t(f"bundle__name--{self.key}")

    @property
    def description(self) -> str:
        return t(f"bundle__description--{self.key}")

    def units(self, quantities: dict[str, int]) -> int:
        pads = quantities.get("brake_pads", 0)
        rotors = quantities.get("brake_rotors", 0)
        suspension = quantities.get("suspension", 0)
        if self.key == "pads_rotors":
            return min(pads, rotors)
        if self.key == "brakes_suspension":
            return min(suspension, max(pads, rotors))
        return 0

    @property
    def discount_per_unit(self) -> Decimal:
        return round_down_5(self.hours_saved_per_unit * LABOR_RATE)


SERVICES: tuple[Service, ...] = (
    Service(
        "brake_pads",
        Decimal("1.0"),
        unit="axle",
        max_quantity=2,
    ),
    Service(
        "brake_rotors",
        Decimal("1.25"),
        unit="axle",
        max_quantity=2,
    ),
    Service(
        "suspension",
        Decimal("2.5"),
        unit="axle",
        max_quantity=2,
    ),
    Service(
        "oil_change",
        Decimal("0.5"),
    ),
    Service(
        "spark_plugs",
        Decimal("1.0"),
    ),
    Service(
        "alternator",
        Decimal("1.5"),
    ),
    Service(
        "belt_replacement",
        Decimal("0.75"),
    ),
    Service(
        "air_filter",
        Decimal("0.25"),
    ),
    Service(
        "other",
        Decimal("0"),
        quote_required=True,
    ),
)

SERVICES_BY_KEY = {service.key: service for service in SERVICES}

BUNDLES: tuple[Bundle, ...] = (
    Bundle(
        "pads_rotors",
        Decimal("0.75"),
    ),
    Bundle(
        "brakes_suspension",
        Decimal("0.5"),
    ),
)


def _sentence(text: str) -> str:
    """Capitalize the first letter (Spanish labels can start with a service name)."""
    return text[:1].upper() + text[1:]


def _hours(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _addon_names() -> str:
    first, second = (SERVICES_BY_KEY[key].name.lower() for key in FREE_ADDON_KEYS)
    return t("list__pair", first=first, second=second)


BUNDLES_BY_KEY = {bundle.key: bundle for bundle in BUNDLES}


def deals() -> list[dict]:
    """Customer-facing descriptions of the visit-level discounts."""
    addons = _addon_names()
    rates = {
        "rate": f"{VOLUME_RATE:.0f}",
        "threshold": f"{VOLUME_THRESHOLD:.0f}",
        "labor_rate": f"{LABOR_RATE:.0f}",
    }
    return [
        {
            "key": "free_addons",
            "name": _sentence(t("deal__name--free-addons", addons=addons)),
            "description": t(
                "deal__description--free-addons", addons=addons, hours=_hours(FREE_ADDON_MIN_HOURS)
            ),
        },
        {
            "key": "volume_rate",
            "name": t("deal__name--volume-rate", **rates),
            "description": t("deal__description--volume-rate", **rates),
        },
    ]


def discount_label(key: str) -> str:
    """Label for a discount line, by its key, in the active language."""
    if key in BUNDLES_BY_KEY:
        return BUNDLES_BY_KEY[key].name
    if key == "volume_rate":
        return t(
            "discount__name--volume-rate",
            rate=f"{VOLUME_RATE:.0f}",
            threshold=f"{VOLUME_THRESHOLD:.0f}",
        )
    service_key = key.removeprefix("free_")
    return _sentence(
        t(
            "discount__name--free-addon",
            service=SERVICES_BY_KEY[service_key].name.lower(),
            hours=_hours(FREE_ADDON_MIN_HOURS),
        )
    )


def localize_estimate(quote: dict) -> dict:
    """Re-render a stored estimate's labels in the active language.

    Estimates are saved with keys; labels follow whoever is reading (the
    customer in Spanish, the mechanic in English).
    """
    if not quote or "line_items" not in quote:
        return quote
    localized = dict(quote)
    localized["line_items"] = [
        {**item, "name": SERVICES_BY_KEY[item["key"]].name} for item in quote["line_items"]
    ]
    localized["discounts"] = [
        {**discount, "name": discount_label(discount["key"])} for discount in quote["discounts"]
    ]
    return localized


def catalog() -> dict:
    """Public, JSON-serializable view of the catalog and booking policy."""
    return {
        "services": [
            {
                "key": s.key,
                "name": s.name,
                "description": s.description,
                "labor_hours": str(s.labor_hours),
                "price": str(s.price),
                "unit": s.unit,
                "max_quantity": s.max_quantity,
                "quote_required": s.quote_required,
            }
            for s in SERVICES
        ],
        "bundles": [
            {
                "key": b.key,
                "name": b.name,
                "description": b.description,
                "discount_per_unit": str(b.discount_per_unit),
            }
            for b in BUNDLES
        ],
        "deals": deals(),
        "labor_rate": str(LABOR_RATE),
        "service_call_fee": str(SERVICE_CALL_FEE),
        "emergency_fee": str(EMERGENCY_FEE),
        "booking_lead_days": BOOKING_LEAD_DAYS,
        "emergency_window_days": EMERGENCY_WINDOW_DAYS,
    }


def normalize_quantities(items: list[dict]) -> dict[str, int]:
    """Collapse validated ``[{"key", "quantity"}]`` items into ``{key: qty}``.

    Callers are expected to have validated keys already; quantities are clamped
    to each service's allowed range.
    """
    quantities: dict[str, int] = {}
    for item in items:
        service = SERVICES_BY_KEY[item["key"]]
        qty = max(1, min(int(item.get("quantity") or 1), service.max_quantity))
        quantities[service.key] = qty
    return quantities


def scheduling(preferred_date: date | None, today: date) -> dict:
    if preferred_date is None:
        return {"days_out": None, "is_emergency": False, "short_notice": False}
    days_out = (preferred_date - today).days
    return {
        "days_out": days_out,
        "is_emergency": days_out < EMERGENCY_WINDOW_DAYS,
        # Inside the standard lead time parts may have to come from a local
        # store at retail price instead of being ordered ahead.
        "short_notice": days_out < BOOKING_LEAD_DAYS,
    }


def estimate(quantities: dict[str, int], preferred_date: date | None, today: date) -> dict:
    """Price a set of services. Labor only; parts are quoted separately.

    Discounts apply in order: per-axle bundles, free add-ons, then the volume
    rate on whatever labor remains.
    """
    line_items = []
    subtotal = Decimal("0.00")
    labor_hours = Decimal("0")
    for service in SERVICES:
        qty = quantities.get(service.key)
        if not qty:
            continue
        amount = service.price * qty
        subtotal += amount
        labor_hours += service.labor_hours * qty
        line_items.append(
            {
                "key": service.key,
                "name": service.name,
                "quantity": qty,
                "unit": service.unit,
                "unit_price": str(service.price),
                "amount": str(amount),
                "quote_required": service.quote_required,
            }
        )

    discounts = []
    discount_total = Decimal("0.00")
    for bundle in BUNDLES:
        units = bundle.units(quantities)
        if units <= 0:
            continue
        amount = bundle.discount_per_unit * units
        discount_total += amount
        labor_hours -= bundle.hours_saved_per_unit * units
        discounts.append(
            {"key": bundle.key, "name": bundle.name, "units": units, "amount": str(amount)}
        )

    # Free add-ons: only when the *other* work is already a long job.
    addon_hours = sum(
        (SERVICES_BY_KEY[key].labor_hours * quantities[key] for key in FREE_ADDON_KEYS if quantities.get(key)),
        Decimal("0"),
    )
    if addon_hours and labor_hours - addon_hours >= FREE_ADDON_MIN_HOURS:
        for key in FREE_ADDON_KEYS:
            if quantities.get(key):
                service = SERVICES_BY_KEY[key]
                amount = service.price * quantities[key]
                discount_total += amount
                discounts.append(
                    {
                        "key": f"free_{key}",
                        "name": discount_label(f"free_{key}"),
                        "units": 1,
                        "amount": str(amount),
                    }
                )

    # Volume rate: labor past the threshold bills at VOLUME_RATE. Labor dollars
    # convert to hours at LABOR_RATE, so the discount is the rate difference.
    net_labor = subtotal - discount_total
    if net_labor > VOLUME_THRESHOLD:
        amount = round_down_5(
            (net_labor - VOLUME_THRESHOLD) * (LABOR_RATE - VOLUME_RATE) / LABOR_RATE
        )
        if amount > 0:
            discount_total += amount
            discounts.append(
                {
                    "key": "volume_rate",
                    "name": discount_label("volume_rate"),
                    "units": 1,
                    "amount": str(amount),
                }
            )

    schedule = scheduling(preferred_date, today)
    has_work = bool(line_items)
    service_call_fee = SERVICE_CALL_FEE if has_work else Decimal("0.00")
    emergency_fee = EMERGENCY_FEE if has_work and schedule["is_emergency"] else Decimal("0.00")
    total = subtotal - discount_total + service_call_fee + emergency_fee

    return {
        "line_items": line_items,
        "discounts": discounts,
        "subtotal": str(subtotal),
        "discount_total": str(discount_total),
        "service_call_fee": str(service_call_fee),
        "emergency_fee": str(emergency_fee),
        "total": str(total),
        "labor_hours": format(labor_hours.normalize(), "f") if labor_hours else "0",
        "needs_custom_quote": any(item["quote_required"] for item in line_items),
        "scheduling": schedule,
    }
