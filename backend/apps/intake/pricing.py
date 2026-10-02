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
* Prices round *up* to the nearest $5 and discounts round *down*, so rounding
  never takes the effective rate below target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

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
    name: str
    description: str
    labor_hours: Decimal
    unit: str | None = None
    max_quantity: int = 1
    quote_required: bool = False

    @property
    def price(self) -> Decimal:
        if self.quote_required:
            return Decimal("0.00")
        return round_up_5(self.labor_hours * LABOR_RATE)


@dataclass(frozen=True)
class Bundle:
    key: str
    name: str
    description: str
    hours_saved_per_unit: Decimal

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
        "Brake pads",
        "Replace pads, clean and lube slides, check fluid.",
        Decimal("1.0"),
        unit="axle",
        max_quantity=2,
    ),
    Service(
        "brake_rotors",
        "Brake rotors",
        "Replace rotors on the axle; pairs well with new pads.",
        Decimal("1.25"),
        unit="axle",
        max_quantity=2,
    ),
    Service(
        "suspension",
        "Suspension (struts / shocks)",
        "Replace struts or shocks on the axle. An alignment afterwards is recommended and not included.",
        Decimal("2.5"),
        unit="axle",
        max_quantity=2,
    ),
    Service(
        "oil_change",
        "Oil change",
        "Drain, new filter, refill, and a quick fluid and tire check.",
        Decimal("0.5"),
    ),
    Service(
        "spark_plugs",
        "Spark plugs",
        "Most 4-cylinder engines. V6/V8 or plugs under the intake may need a custom quote.",
        Decimal("1.0"),
    ),
    Service(
        "alternator",
        "Alternator",
        "Remove and replace the alternator, test charging output.",
        Decimal("1.5"),
    ),
    Service(
        "belt_replacement",
        "Belt replacement (serpentine)",
        "Serpentine/accessory belt. Timing belts are quoted separately.",
        Decimal("0.75"),
    ),
    Service(
        "air_filter",
        "Air filter",
        "Engine air filter; cabin filter on request.",
        Decimal("0.25"),
    ),
    Service(
        "other",
        "Other (may not be covered)",
        "Describe the problem and I'll let you know if it's something I can take on.",
        Decimal("0"),
        quote_required=True,
    ),
)

SERVICES_BY_KEY = {service.key: service for service in SERVICES}

BUNDLES: tuple[Bundle, ...] = (
    Bundle(
        "pads_rotors",
        "Pads + rotors bundle",
        "Rotors come off anyway when pads are replaced, so the second job is mostly free time.",
        Decimal("0.75"),
    ),
    Bundle(
        "brakes_suspension",
        "Brakes + suspension bundle",
        "The wheel and caliper are already off, so suspension work on the same axle goes faster.",
        Decimal("0.5"),
    ),
)


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
    """Price a set of services. Labor only; parts are quoted separately."""
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
