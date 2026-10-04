"""Product catalog and pricing rules for dirt and topsoil delivery.

This module is the single source of truth for prices. The frontend reads the
catalog from `/api/v1/intake/catalog/` and asks `/api/v1/intake/estimate/` for
live quotes, and the order endpoint re-prices every submission here, so a
price change only ever needs to happen in this file.

How prices are built
--------------------
* Material is priced per cubic yard (``Product.price_per_yard``).
* Delivery is priced per truckload. An order bigger than one truck holds is
  split into several loads by the dispatcher (dispatch.py), and each load pays
  ``DELIVERY_BASE_FEE`` (which covers the first ``INCLUDED_MILES`` from the
  yard it ships from) plus ``PER_MILE_FEE`` for every mile past that.
* Delivery today or tomorrow (inside ``RUSH_WINDOW_DAYS``) adds one
  ``RUSH_FEE`` per order: it means reshuffling a truck's day.
* Sales tax (``SALES_TAX_RATE``) applies to material only. It's 0 until you
  set it for your area.
* Delivery fees round *up* to the nearest $5.

Which yard a load ships from, and on which truck, is decided by dispatch.py
from the service-area table (data/service_area.json); this module only turns
the resulting loads into money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .i18n import t

# --- Business inputs (edit these) ------------------------------------------

DELIVERY_BASE_FEE = Decimal("75.00")
"""Per truckload; covers the first ``INCLUDED_MILES`` from the yard."""

INCLUDED_MILES = Decimal("10")

PER_MILE_FEE = Decimal("3.50")
"""Per load, for each mile past ``INCLUDED_MILES`` (one way, yard to site)."""

RUSH_WINDOW_DAYS = 2
"""Orders for a date fewer than this many days out are rush (today, tomorrow)."""

RUSH_FEE = Decimal("50.00")

SALES_TAX_RATE = Decimal("0")
"""Applied to material only, e.g. Decimal("0.0725"). 0 = no tax line."""

DELIVERY_WEEKDAYS = (0, 1, 2, 3, 4, 5)
"""Days trucks run (Monday = 0). Sunday is off."""

MAX_DAYS_AHEAD = 90
"""How far ahead customers can pick a delivery date."""

# --- Products -----------------------------------------------------------------

_FIVE = Decimal("5")
CENTS = Decimal("0.01")


def round_up_5(amount: Decimal) -> Decimal:
    return ((amount / _FIVE).to_integral_value(rounding=ROUND_CEILING) * _FIVE).quantize(CENTS)


@dataclass(frozen=True)
class Product:
    key: str
    price_per_yard: Decimal
    min_yards: int = 1
    max_yards: int = 60

    # Labels come from the text map in the active language (see i18n.py).
    @property
    def name(self) -> str:
        return t(f"product__name--{self.key}")

    @property
    def description(self) -> str:
        return t(f"product__description--{self.key}")


PRODUCTS: tuple[Product, ...] = (
    Product("screened_topsoil", Decimal("42.00")),
    Product("garden_blend", Decimal("58.00")),
    Product("compost", Decimal("48.00")),
    Product("fill_dirt", Decimal("18.00"), min_yards=5),
    Product("washed_sand", Decimal("45.00")),
)

PRODUCTS_BY_KEY = {product.key: product for product in PRODUCTS}
PRODUCT_CHOICES = [(p.key, p.key.replace("_", " ").capitalize()) for p in PRODUCTS]


# --- Helpers --------------------------------------------------------------------


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP))


def delivery_fee(miles: Decimal | float | str) -> Decimal:
    """What one truckload costs to deliver from ``miles`` away (one way)."""
    extra = max(Decimal("0"), Decimal(str(miles)) - INCLUDED_MILES)
    return round_up_5(DELIVERY_BASE_FEE + extra * PER_MILE_FEE)


def normalize_quantities(items: list[dict], clamp: bool = True) -> dict[str, int]:
    """Collapse validated ``[{"key", "quantity"}]`` items into ``{key: yards}``.

    Callers are expected to have validated keys already. Quantities are clamped
    to each product's order range unless ``clamp`` is off (invoices record what
    was actually delivered). Catalog order is kept.
    """
    given = {item["key"]: int(item.get("quantity") or 0) for item in items}
    quantities: dict[str, int] = {}
    for product in PRODUCTS:
        if product.key in given:
            qty = given[product.key]
            quantities[product.key] = max(product.min_yards, min(qty, product.max_yards)) if clamp else max(1, qty)
    return quantities


def item_list(items: dict) -> list[dict]:
    """Stored ``{key: yards}`` -> ``[{key, name, quantity}]`` in catalog order."""
    items = items or {}
    return [
        {"key": p.key, "name": p.name, "quantity": items[p.key]}
        for p in PRODUCTS
        if p.key in items
    ]


def is_delivery_day(day: date) -> bool:
    return day.weekday() in DELIVERY_WEEKDAYS


def scheduling(preferred_date: date | None, today: date) -> dict:
    if preferred_date is None:
        return {"days_out": None, "is_rush": False}
    days_out = (preferred_date - today).days
    return {"days_out": days_out, "is_rush": days_out < RUSH_WINDOW_DAYS}


def catalog() -> dict:
    """Public, JSON-serializable view of the products and delivery policy."""
    return {
        "products": [
            {
                "key": p.key,
                "name": p.name,
                "description": p.description,
                "price_per_yard": str(p.price_per_yard),
                "min_yards": p.min_yards,
                "max_yards": p.max_yards,
            }
            for p in PRODUCTS
        ],
        "delivery_base_fee": str(DELIVERY_BASE_FEE),
        "included_miles": str(INCLUDED_MILES),
        "per_mile_fee": str(PER_MILE_FEE),
        "rush_fee": str(RUSH_FEE),
        "rush_window_days": RUSH_WINDOW_DAYS,
        "delivery_weekdays": list(DELIVERY_WEEKDAYS),
        "max_days_ahead": MAX_DAYS_AHEAD,
        "sales_tax_rate": str(SALES_TAX_RATE),
    }


# --- Quotes ---------------------------------------------------------------------


def quote(
    quantities: dict[str, int],
    loads: list[dict],
    preferred_date: date | None,
    today: date,
    rush: bool | None = None,
) -> dict:
    """Price material plus delivery.

    ``loads`` are the truckloads dispatch.py planned: dicts with ``product``,
    ``quantity`` and ``miles``. ``rush`` overrides the rush fee the date would
    imply (invoices use it: staff decide whether it applies).
    """
    line_items = []
    material = Decimal("0.00")
    for product in PRODUCTS:
        qty = quantities.get(product.key)
        if not qty:
            continue
        amount = product.price_per_yard * qty
        material += amount
        line_items.append(
            {
                "key": product.key,
                "name": product.name,
                "quantity": qty,
                "unit_price": str(product.price_per_yard),
                "amount": _money(amount),
            }
        )

    deliveries = []
    delivery_total = Decimal("0.00")
    for load in loads:
        fee = delivery_fee(load["miles"])
        delivery_total += fee
        deliveries.append(
            {
                "product": load["product"],
                "quantity": load["quantity"],
                "miles": str(Decimal(str(load["miles"])).quantize(Decimal("0.1"))),
                "fee": _money(fee),
            }
        )

    schedule = scheduling(preferred_date, today)
    if rush is not None:
        schedule["is_rush"] = rush
    has_material = bool(line_items)
    rush_fee = RUSH_FEE if has_material and schedule["is_rush"] else Decimal("0.00")
    tax = (material * SALES_TAX_RATE).quantize(CENTS, rounding=ROUND_HALF_UP)
    total = material + tax + delivery_total + rush_fee

    return {
        "line_items": line_items,
        "deliveries": deliveries,
        "material_total": _money(material),
        "tax": _money(tax),
        "delivery_total": _money(delivery_total),
        "rush_fee": _money(rush_fee),
        "total": _money(total),
        "load_count": len(deliveries),
        "scheduling": schedule,
    }


def localize_quote(stored: dict) -> dict:
    """Re-render a stored quote's labels in the active language.

    Quotes are saved with keys; labels follow whoever is reading (the customer
    in Spanish, staff in English).
    """
    if not stored or "line_items" not in stored:
        return stored
    localized = dict(stored)
    localized["line_items"] = [
        {**item, "name": PRODUCTS_BY_KEY[item["key"]].name}
        for item in stored["line_items"]
        if item["key"] in PRODUCTS_BY_KEY
    ]
    localized["deliveries"] = [
        {**load, "product_name": PRODUCTS_BY_KEY[load["product"]].name}
        for load in stored.get("deliveries", [])
        if load["product"] in PRODUCTS_BY_KEY
    ]
    return localized
