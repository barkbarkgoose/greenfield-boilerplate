"""Dispatch: which yard and truck deliver each load of an order.

Inputs
------
* The customer's zip code -> the service-area table (service_area.py) says
  whether we deliver there and how far it is from each yard.
* ``YardStock`` -> which of those yards has each product right now.
* ``Truck`` / ``TruckDayOff`` -> which trucks run on the date, and how big a
  load each carries.
* ``OrderLoad`` rows already booked for the date -> how much of each truck's
  day is spoken for.

How an order is routed
----------------------
Each product travels separately (a dump bed carries one material), so every
product is split into truckloads:

1. Candidate sources are the yards listed for the zip that stock the product.
2. For the yards' trucks that are running that day, each load costs truck
   time: ``LOAD_HANDLING_MINUTES`` (loading + dumping) plus the round trip.
   A truck can take a load only if its remaining ``workday_minutes`` cover it.
3. The next load goes to the truck that could deliver what's left of the
   product in the least total truck time (so one big truck from a slightly
   farther yard beats three trips in a small one), ties going to the nearer
   yard and then the bigger truck.
4. Repeat until the product is fully loaded.

If no truck has room, the rest is still priced (from the nearest stocking
yard, in standard-size loads) but left unassigned and the plan is marked
``no_capacity``, with the next date that would work. A product nobody stocks
makes the plan ``out_of_stock``. Either way the order can still be taken:
staff see the flag and sort it out.

This is deliberately simple: one load = one truck trip from its home yard,
no multi-stop routes, no time slots. docs/scheduling-and-dispatch.md covers
what a fuller scheduler would add.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from . import pricing, service_area
from .models import Order, OrderLoad, Truck, TruckDayOff, Yard, YardStock

LOAD_HANDLING_MINUTES = 30
"""Loading at the yard plus dumping on site, per load."""

DEFAULT_LOAD_YARDS = 10
"""Load size used to price loads no truck could take."""

NEXT_DATE_SEARCH_DAYS = 21
"""How far past a full date to look for the next one that works."""

OK = "ok"
NO_CAPACITY = "no_capacity"
OUT_OF_STOCK = "out_of_stock"
SPECIAL_REQUEST = "special_request"
OUTSIDE_AREA = "outside_area"
EMPTY = "empty"


@dataclass
class PlannedLoad:
    product: str
    quantity: int
    yard: Yard | None
    truck: Truck | None
    miles: Decimal
    minutes: int  # truck time this load takes

    @property
    def assigned(self) -> bool:
        return self.truck is not None

    def as_dict(self) -> dict:
        return {
            "product": self.product,
            "quantity": self.quantity,
            "yard": self.yard.code if self.yard else None,
            "yard_name": self.yard.name if self.yard else "",
            "truck": self.truck.id if self.truck else None,
            "truck_name": self.truck.name if self.truck else "",
            "miles": str(self.miles),
            "minutes": self.minutes,
            "assigned": self.assigned,
        }


@dataclass
class Plan:
    status: str
    area: service_area.Area
    day: date | None
    loads: list[PlannedLoad] = field(default_factory=list)
    problems: list[dict] = field(default_factory=list)
    next_available_date: date | None = None

    @property
    def priceable(self) -> bool:
        return self.status in (OK, NO_CAPACITY, OUT_OF_STOCK)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "zip_code": self.area.zip_code,
            "coverage": self.area.status,
            "city": self.area.city,
            "date": self.day.isoformat() if self.day else None,
            "loads": [load.as_dict() for load in self.loads],
            "problems": self.problems,
            "next_available_date": self.next_available_date.isoformat() if self.next_available_date else None,
        }


def load_minutes(one_way_minutes: int) -> int:
    return LOAD_HANDLING_MINUTES + 2 * one_way_minutes


class Network:
    """A snapshot of yards, stock, trucks and booked truck time.

    Loaded once per plan (or per day on the dispatch board) so routing an
    order, and searching ahead for a free date, costs a handful of queries.
    """

    def __init__(self, start: date | None, days: int = 1, exclude_order_id: int | None = None):
        self.yards = {yard.code: yard for yard in Yard.objects.filter(active=True)}
        self.stock = set(
            YardStock.objects.filter(in_stock=True, yard__active=True).values_list("yard__code", "product")
        )
        self.trucks: dict[str, list[Truck]] = defaultdict(list)
        for truck in Truck.objects.filter(active=True, yard__active=True).select_related("yard"):
            self.trucks[truck.yard.code].append(truck)

        self.days_off: set[tuple[int, date]] = set()
        self.used: dict[tuple[int, date], int] = defaultdict(int)
        if start is not None:
            end = start + timedelta(days=days)
            self.days_off = set(
                TruckDayOff.objects.filter(date__gte=start, date__lt=end).values_list("truck_id", "date")
            )
            booked = OrderLoad.objects.filter(
                date__gte=start, date__lt=end, truck__isnull=False
            ).exclude(order__status=Order.Status.DECLINED)
            if exclude_order_id:
                booked = booked.exclude(order_id=exclude_order_id)
            for truck_id, day, minutes in booked.values_list("truck_id", "date", "minutes"):
                self.used[(truck_id, day)] += minutes

    def trucks_running(self, yard_code: str, day: date | None) -> list[Truck]:
        if day is not None and not pricing.is_delivery_day(day):
            return []
        return [t for t in self.trucks.get(yard_code, []) if day is None or (t.id, day) not in self.days_off]

    def free_minutes(self, truck: Truck, day: date, usage: dict) -> int:
        return truck.workday_minutes - usage.get((truck.id, day), 0)


def _route(quantities: dict[str, int], area: service_area.Area, day: date | None, network: Network):
    """Split each product into loads and give each a yard and truck."""
    usage = dict(network.used)
    loads: list[PlannedLoad] = []
    problems: list[dict] = []

    for product, quantity in quantities.items():
        sources = [d for d in area.yards if d.code in network.yards and (d.code, product) in network.stock]
        if not sources:
            problems.append({"code": OUT_OF_STOCK, "product": product})
            # Still price it from the nearest yard so the customer sees a number.
            nearest = next((d for d in area.yards if d.code in network.yards), None)
            if nearest:
                for size in _split(quantity, DEFAULT_LOAD_YARDS):
                    loads.append(PlannedLoad(product, size, None, None, nearest.miles, load_minutes(nearest.minutes)))
            continue

        remaining = quantity
        while remaining > 0:
            best = None
            for source in sources:
                cost = load_minutes(source.minutes)
                for truck in network.trucks_running(source.code, day):
                    if day is not None and network.free_minutes(truck, day, usage) < cost:
                        continue
                    trips = math.ceil(remaining / truck.capacity_yards)
                    key = (trips * cost, source.minutes, -truck.capacity_yards, truck.id)
                    if best is None or key < best[0]:
                        best = (key, source, truck, cost)
            if best is None:
                problems.append({"code": NO_CAPACITY, "product": product, "quantity": remaining})
                source = sources[0]
                size = max((t.capacity_yards for t in network.trucks.get(source.code, [])), default=DEFAULT_LOAD_YARDS)
                for part in _split(remaining, size):
                    loads.append(
                        PlannedLoad(product, part, network.yards[source.code], None, source.miles, load_minutes(source.minutes))
                    )
                break
            _, source, truck, cost = best
            size = min(remaining, truck.capacity_yards)
            if day is not None:
                usage[(truck.id, day)] = usage.get((truck.id, day), 0) + cost
            loads.append(PlannedLoad(product, size, network.yards[source.code], truck, source.miles, cost))
            remaining -= size

    return loads, problems


def _split(quantity: int, size: int) -> list[int]:
    size = max(1, size)
    full, rest = divmod(quantity, size)
    return [size] * full + ([rest] if rest else [])


def _status(problems: list[dict]) -> str:
    codes = {p["code"] for p in problems}
    if OUT_OF_STOCK in codes:
        return OUT_OF_STOCK
    if NO_CAPACITY in codes:
        return NO_CAPACITY
    return OK


def plan(
    quantities: dict[str, int],
    zip_code: str | None,
    day: date | None,
    *,
    exclude_order_id: int | None = None,
    search_ahead: bool = True,
) -> Plan:
    """Route an order (without saving anything). See the module docstring."""
    area = service_area.lookup(zip_code)
    if area.status == service_area.OUTSIDE:
        return Plan(OUTSIDE_AREA, area, day)
    if area.status == service_area.CONTACT:
        return Plan(SPECIAL_REQUEST, area, day)
    if not quantities:
        return Plan(EMPTY, area, day)

    window = NEXT_DATE_SEARCH_DAYS + 1 if search_ahead else 1
    network = Network(day, window, exclude_order_id)
    loads, problems = _route(quantities, area, day, network)
    result = Plan(_status(problems), area, day, loads, problems)

    if result.status == NO_CAPACITY and day is not None and search_ahead:
        for offset in range(1, NEXT_DATE_SEARCH_DAYS + 1):
            candidate = day + timedelta(days=offset)
            if not pricing.is_delivery_day(candidate):
                continue
            _, later_problems = _route(quantities, area, candidate, network)
            if not later_problems:
                result.next_available_date = candidate
                break
    return result


def pricing_loads(result: Plan) -> list[dict]:
    """The plan's loads in the shape pricing.quote expects."""
    return [{"product": l.product, "quantity": l.quantity, "miles": l.miles} for l in result.loads]


def localize(plan_data: dict) -> dict:
    """Add product names (active language) to a plan's loads and problems."""
    def name(key):
        product = pricing.PRODUCTS_BY_KEY.get(key)
        return product.name if product else key

    localized = dict(plan_data)
    localized["loads"] = [{**load, "product_name": name(load["product"])} for load in plan_data.get("loads", [])]
    localized["problems"] = [{**p, "product_name": name(p.get("product"))} for p in plan_data.get("problems", [])]
    return localized


# --- Saving plans on orders -------------------------------------------------------


@transaction.atomic
def assign(order: Order) -> Plan:
    """(Re)route an order and save its loads, replacing any it had."""
    result = plan(
        order.items or {},
        order.zip_code,
        order.delivery_date,
        exclude_order_id=order.pk,
        search_ahead=False,
    )
    order.loads.all().delete()
    OrderLoad.objects.bulk_create(
        OrderLoad(
            order=order,
            product=load.product,
            quantity=load.quantity,
            yard=load.yard,
            truck=load.truck,
            date=order.delivery_date,
            miles=load.miles,
            minutes=load.minutes,
            sequence=index,
        )
        for index, load in enumerate(result.loads)
    )
    order.plan_status = result.status if result.priceable else Order.PlanStatus.NONE
    order.save(update_fields=["plan_status", "updated_at"])
    return result


def move_to_date(order: Order) -> None:
    """Keep the loads (and any hand assignments) but book them on the new date."""
    order.loads.update(date=order.delivery_date)


def reassign_load(load: OrderLoad, truck: Truck | None) -> OrderLoad:
    """Put a load on another truck (from that truck's yard), or unassign it.

    Raises ValueError when the truck's yard has no saved distance to the zip.
    """
    if truck is None:
        load.truck = None
    else:
        distance = service_area.lookup(load.order.zip_code).distance_to(truck.yard.code)
        if distance is None:
            raise ValueError(truck.yard.name)
        load.truck, load.yard = truck, truck.yard
        load.miles, load.minutes = distance.miles, load_minutes(distance.minutes)
    load.save(update_fields=["truck", "yard", "miles", "minutes"])
    refresh_plan_status(load.order)
    return load


def refresh_plan_status(order: Order) -> None:
    loads = list(order.loads.all())
    if not loads:
        status = Order.PlanStatus.NONE
    elif all(load.truck_id for load in loads):
        status = Order.PlanStatus.OK
    else:
        status = Order.PlanStatus.NO_CAPACITY
    if order.plan_status != status:
        order.plan_status = status
        order.save(update_fields=["plan_status", "updated_at"])


# --- The dispatch board -------------------------------------------------------------


def day_board(day: date) -> dict:
    """Everything the dispatch board shows for one day: trucks, loads, stock."""
    network = Network(day)
    loads = list(
        OrderLoad.objects.filter(date=day)
        .exclude(order__status=Order.Status.DECLINED)
        .select_related("order", "truck", "yard")
        .order_by("truck_id", "order__delivery_window", "order_id", "sequence")
    )
    by_truck: dict[int, list[OrderLoad]] = defaultdict(list)
    unassigned = []
    for load in loads:
        (by_truck[load.truck_id] if load.truck_id else unassigned).append(load)

    def load_row(load: OrderLoad) -> dict:
        order = load.order
        return {
            "id": load.id,
            "order_id": order.id,
            "order_name": order.name,
            "order_status": order.status,
            "zip_code": order.zip_code,
            "city": service_area.lookup(order.zip_code).city,
            "window": order.delivery_window,
            "product": load.product,
            "product_name": pricing.PRODUCTS_BY_KEY[load.product].name if load.product in pricing.PRODUCTS_BY_KEY else load.product,
            "quantity": load.quantity,
            "yard": load.yard.code if load.yard else None,
            "miles": str(load.miles),
            "minutes": load.minutes,
        }

    yards = []
    for yard in Yard.objects.prefetch_related("stock", "trucks").order_by("name"):
        trucks = []
        for truck in yard.trucks.all():
            truck_loads = by_truck.get(truck.id, [])
            used = sum(load.minutes for load in truck_loads)
            trucks.append(
                {
                    "id": truck.id,
                    "name": truck.name,
                    "capacity_yards": truck.capacity_yards,
                    "workday_minutes": truck.workday_minutes,
                    "active": truck.active,
                    "day_off": (truck.id, day) in network.days_off,
                    "used_minutes": used,
                    "loads": [load_row(load) for load in truck_loads],
                }
            )
        stock = {row.product: row for row in yard.stock.all()}
        yards.append(
            {
                "code": yard.code,
                "name": yard.name,
                "active": yard.active,
                "stock": [
                    {
                        "id": stock[p.key].id if p.key in stock else None,
                        "product": p.key,
                        "product_name": p.name,
                        "carried": p.key in stock,
                        "in_stock": stock[p.key].in_stock if p.key in stock else False,
                        "note": stock[p.key].note if p.key in stock else "",
                    }
                    for p in pricing.PRODUCTS
                ],
                "trucks": trucks,
            }
        )
    return {
        "date": day.isoformat(),
        "delivery_day": pricing.is_delivery_day(day),
        "yards": yards,
        "unassigned": [load_row(load) for load in unassigned],
    }
