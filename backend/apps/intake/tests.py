"""Tests for pricing, the service-area lookup, dispatch and the public endpoints."""

import json
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.intake import dispatch, pricing, service_area
from apps.intake.conftest import delivery_day
from apps.intake.management.commands.build_service_area import build, haversine_miles
from apps.intake.models import Order, OrderLoad, TruckDayOff, YardStock

TODAY = date(2026, 10, 5)  # a Monday


def loads_of(plan):
    return [(l.product, l.quantity, l.yard.code if l.yard else None, l.truck.name if l.truck else None) for l in plan.loads]


class TestPricing:
    def test_delivery_fee_by_distance(self):
        assert pricing.delivery_fee(4) == pricing.DELIVERY_BASE_FEE
        assert pricing.delivery_fee(pricing.INCLUDED_MILES) == pricing.DELIVERY_BASE_FEE
        # 12 mi: 2 extra miles at $3.50 = $82, rounded up to $85.
        assert pricing.delivery_fee(12) == Decimal("85.00")
        assert pricing.delivery_fee("20") == Decimal("110.00")

    def test_quote_adds_material_and_each_load(self):
        loads = [{"product": "screened_topsoil", "quantity": 14, "miles": 12}, {"product": "screened_topsoil", "quantity": 6, "miles": 4}]
        quote = pricing.quote({"screened_topsoil": 20}, loads, TODAY + timedelta(days=7), TODAY)
        assert quote["material_total"] == "840.00"
        assert quote["delivery_total"] == "160.00"
        assert quote["total"] == "1000.00"
        assert quote["load_count"] == 2
        assert quote["rush_fee"] == "0.00" and quote["tax"] == "0.00"

    def test_rush_fee_for_today_and_tomorrow(self):
        loads = [{"product": "compost", "quantity": 3, "miles": 5}]
        tomorrow = pricing.quote({"compost": 3}, loads, TODAY + timedelta(days=1), TODAY)
        assert tomorrow["scheduling"]["is_rush"] and tomorrow["rush_fee"] == str(pricing.RUSH_FEE)
        later = pricing.quote({"compost": 3}, loads, TODAY + timedelta(days=2), TODAY)
        assert not later["scheduling"]["is_rush"]
        # Invoices decide for themselves.
        assert pricing.quote({"compost": 3}, loads, None, TODAY, rush=True)["rush_fee"] == str(pricing.RUSH_FEE)

    def test_sales_tax_on_material_only(self, monkeypatch):
        monkeypatch.setattr(pricing, "SALES_TAX_RATE", Decimal("0.10"))
        quote = pricing.quote({"compost": 2}, [{"product": "compost", "quantity": 2, "miles": 4}], None, TODAY)
        assert quote["tax"] == "9.60"
        assert quote["total"] == str(Decimal("96.00") + Decimal("9.60") + pricing.DELIVERY_BASE_FEE)

    def test_normalize_clamps_to_order_range(self):
        assert pricing.normalize_quantities([{"key": "fill_dirt", "quantity": 2}]) == {"fill_dirt": 5}
        assert pricing.normalize_quantities([{"key": "fill_dirt", "quantity": 2}], clamp=False) == {"fill_dirt": 2}
        # Catalog order, whatever order they came in.
        items = [{"key": "washed_sand", "quantity": 1}, {"key": "screened_topsoil", "quantity": 3}]
        assert list(pricing.normalize_quantities(items)) == ["screened_topsoil", "washed_sand"]

    def test_no_sunday_delivery(self):
        assert not pricing.is_delivery_day(date(2026, 10, 4))
        assert pricing.is_delivery_day(date(2026, 10, 3))

    def test_localized_quote_follows_language(self):
        from django.utils import translation

        quote = pricing.quote({"compost": 2}, [{"product": "compost", "quantity": 2, "miles": 4}], None, TODAY)
        with translation.override("es"):
            localized = pricing.localize_quote(quote)
        assert localized["line_items"][0]["name"] == "Composta"
        assert localized["deliveries"][0]["product_name"] == "Composta"


class TestServiceArea:
    def test_lookup_statuses(self):
        served = service_area.lookup("80202-1234")
        assert served.status == "serve" and served.city == "Denver"
        assert [y.code for y in served.yards] == ["north", "south"]  # nearest first
        assert served.distance_to("south").miles == Decimal("20")
        contact = service_area.lookup("80403")
        assert contact.status == "contact" and contact.note == "Canyon roads" and contact.yards == ()
        assert service_area.lookup("99999").status == "outside"
        assert service_area.lookup("abc").status == "outside"

    def test_file_changes_are_picked_up(self, settings, tmp_path):
        path = tmp_path / "other.json"
        path.write_text(json.dumps({"zips": {"10001": {"status": "contact"}}}))
        settings.SERVICE_AREA_FILE = str(path)
        assert service_area.lookup("10001").status == "contact"
        assert service_area.lookup("80202").status == "outside"

    def test_validate_reports_mistakes(self):
        problems = service_area.validate(
            {
                "zips": {
                    "1234": {"status": "serve", "yards": {"north": {"miles": 1, "minutes": 2}}},
                    "80202": {"status": "serve"},
                    "80203": {"status": "maybe"},
                    "80204": {"status": "serve", "yards": {"moon": {"miles": "x", "minutes": 3}}},
                }
            },
            {"north"},
        )
        text = "\n".join(problems)
        assert "1234: not a 5-digit" in text
        assert "80202: served but no yards" in text
        assert '80203: status must be "serve" or "contact"' in text
        assert "80204: unknown yard 'moon'" in text and "numeric miles" in text

    def test_bundled_sample_is_valid(self):
        data = json.loads(service_area.DEFAULT_FILE.read_text())
        assert service_area.validate(data, {"north", "south", "west"}) == []


class TestBuildServiceArea:
    yards = {"a": (39.75, -105.0)}

    def test_haversine(self):
        # One degree of latitude is about 69 miles.
        assert 68.5 < haversine_miles(39, -105, 40, -105) < 69.5

    def test_serve_contact_decline_by_distance(self):
        zips = [
            {"zip": "80001", "lat": "39.80", "lng": "-105.0", "city": "Near"},   # ~4.5 road mi
            {"zip": "80002", "lat": "40.05", "lng": "-105.0"},                   # ~27 road mi
            {"zip": "80003", "lat": "40.50", "lng": "-105.0"},                   # far
            {"zip": "80004", "lat": "39.76", "lng": "-105.0", "status": "contact", "note": "Hill"},
        ]
        doc = build(zips, self.yards, road_factor=1.3, serve_miles=20, contact_miles=35)["zips"]
        assert doc["80001"]["status"] == "serve" and doc["80001"]["city"] == "Near"
        assert 4 < doc["80001"]["yards"]["a"]["miles"] < 5
        assert doc["80002"] == {"status": "contact"}
        assert "80003" not in doc
        assert doc["80004"] == {"status": "contact", "note": "Hill"}

    def test_locked_entries_survive_a_rebuild(self):
        existing = {"zips": {"80001": {"status": "serve", "locked": True, "yards": {"a": {"miles": 9.9, "minutes": 33}}}}}
        doc = build([{"zip": "80001", "lat": "39.80", "lng": "-105.0"}], self.yards, existing=existing)
        assert doc["zips"]["80001"]["yards"]["a"] == {"miles": 9.9, "minutes": 33}

    def test_command_writes_a_valid_file(self, tmp_path):
        zips, yards, out = tmp_path / "z.csv", tmp_path / "y.csv", tmp_path / "out.json"
        zips.write_text("zip,lat,lng,city\n80001,39.80,-105.0,Near\n")
        yards.write_text("code,lat,lng\na,39.75,-105.0\n")
        call_command("build_service_area", str(zips), yards=str(yards), out=str(out), stdout=StringIO())
        data = json.loads(out.read_text())
        assert service_area.validate(data) == []
        assert '"a": {"miles":' in out.read_text()  # one line per yard


@pytest.mark.django_db
class TestCheckCommand:
    def test_unknown_yard_fails(self, network, settings, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"zips": {"80202": {"status": "serve", "yards": {"mars": {"miles": 1, "minutes": 2}}}}}))
        with pytest.raises(CommandError):
            call_command("check_service_area", str(path), stdout=StringIO(), stderr=StringIO())

    def test_ok(self, network):
        out = StringIO()
        call_command("check_service_area", stdout=out)
        assert "OK. 2 served, 1 special request" in out.getvalue()


@pytest.mark.django_db
class TestDispatch:
    def test_one_big_truck_from_the_nearest_yard(self, network):
        plan = dispatch.plan({"screened_topsoil": 10}, "80202", TODAY)
        assert plan.status == "ok"
        assert loads_of(plan) == [("screened_topsoil", 10, "north", "N1")]
        assert plan.loads[0].minutes == dispatch.LOAD_HANDLING_MINUTES + 2 * 20

    def test_big_orders_split_into_loads(self, network):
        plan = dispatch.plan({"screened_topsoil": 20}, "80202", TODAY)
        assert loads_of(plan) == [("screened_topsoil", 14, "north", "N1"), ("screened_topsoil", 6, "north", "N1")]

    def test_product_comes_from_the_yard_that_has_it(self, network):
        plan = dispatch.plan({"screened_topsoil": 4, "compost": 3}, "80202", TODAY)
        assert loads_of(plan) == [("screened_topsoil", 4, "north", "N1"), ("compost", 3, "south", "S1")]

    def test_out_of_stock_moves_to_the_next_yard(self, network):
        YardStock.objects.filter(yard__code="north", product="screened_topsoil").update(in_stock=False)
        plan = dispatch.plan({"screened_topsoil": 10}, "80202", TODAY)
        assert loads_of(plan) == [("screened_topsoil", 10, "south", "S1")]

    def test_nobody_stocks_it(self, network):
        YardStock.objects.filter(product="compost").update(in_stock=False)
        plan = dispatch.plan({"compost": 3}, "80202", TODAY)
        assert plan.status == "out_of_stock"
        assert plan.problems == [{"code": "out_of_stock", "product": "compost"}]
        # Still priced from the nearest yard, so the customer sees a number.
        assert loads_of(plan) == [("compost", 3, None, None)] and plan.loads[0].miles == Decimal("12")

    def test_yard_not_listed_for_zip_never_delivers(self, network):
        # Only the west yard has sand, and it isn't listed for 80202.
        assert dispatch.plan({"washed_sand": 2}, "80202", TODAY).status == "out_of_stock"
        assert dispatch.plan({"washed_sand": 2}, "80002", TODAY).status == "ok"

    def test_busy_truck_is_skipped(self, network):
        order = Order.objects.create(name="Earlier", items={"fill_dirt": 14}, zip_code="80202", preferred_date=TODAY)
        OrderLoad.objects.create(order=order, product="fill_dirt", quantity=14, truck=network.trucks["N1"],
                                 yard=network.yards["north"], date=TODAY, minutes=550)  # fmt: skip
        plan = dispatch.plan({"screened_topsoil": 10}, "80202", TODAY)
        # N1 has 50 minutes left; one S1 trip (100 min) beats two N2 trips (140).
        assert loads_of(plan) == [("screened_topsoil", 10, "south", "S1")]
        # Declined orders don't hold trucks.
        order.status = Order.Status.DECLINED
        order.save()
        assert loads_of(dispatch.plan({"screened_topsoil": 10}, "80202", TODAY))[0][3] == "N1"

    def test_an_order_does_not_compete_with_itself(self, network):
        order = Order.objects.create(name="Me", items={"screened_topsoil": 10}, zip_code="80202", preferred_date=TODAY)
        OrderLoad.objects.create(order=order, product="screened_topsoil", quantity=10, truck=network.trucks["N1"], date=TODAY, minutes=590)
        plan = dispatch.plan(order.items, order.zip_code, TODAY, exclude_order_id=order.id)
        assert loads_of(plan)[0][3] == "N1"

    def test_no_capacity_finds_the_next_date(self, network):
        for truck in network.trucks.values():
            TruckDayOff.objects.create(truck=truck, date=TODAY)
        plan = dispatch.plan({"screened_topsoil": 10}, "80202", TODAY)
        assert plan.status == "no_capacity"
        assert loads_of(plan) == [("screened_topsoil", 10, "north", None)]
        assert plan.next_available_date == TODAY + timedelta(days=1)

    def test_inactive_trucks_and_sundays(self, network):
        network.trucks["N1"].active = False
        network.trucks["N1"].save()
        assert loads_of(dispatch.plan({"screened_topsoil": 10}, "80202", TODAY))[0][3] == "S1"
        sunday = dispatch.plan({"screened_topsoil": 10}, "80202", date(2026, 10, 4))
        assert sunday.status == "no_capacity" and sunday.next_available_date == TODAY

    def test_special_request_and_outside(self, network):
        assert dispatch.plan({"compost": 3}, "80403", TODAY).status == "special_request"
        assert dispatch.plan({"compost": 3}, "99999", TODAY).status == "outside_area"

    def test_assign_saves_loads_and_reassign(self, network):
        order = Order.objects.create(name="X", items={"screened_topsoil": 20}, zip_code="80202", preferred_date=TODAY)
        dispatch.assign(order)
        assert order.plan_status == "ok"
        assert [(l.quantity, l.truck.name, l.date) for l in order.loads.all()] == [(14, "N1", TODAY), (6, "N1", TODAY)]

        load = order.loads.last()
        dispatch.reassign_load(load, network.trucks["S1"])
        load.refresh_from_db()
        assert (load.yard.code, load.miles, load.minutes) == ("south", Decimal("20.0"), 100)
        with pytest.raises(ValueError):
            dispatch.reassign_load(load, network.trucks["W1"])  # west isn't listed for 80202
        dispatch.reassign_load(load, None)
        order.refresh_from_db()
        assert order.plan_status == "no_capacity"

    def test_day_board(self, network):
        order = Order.objects.create(name="Board", items={"screened_topsoil": 6}, zip_code="80202", preferred_date=TODAY)
        dispatch.assign(order)
        board = dispatch.day_board(TODAY)
        north = next(y for y in board["yards"] if y["code"] == "north")
        n1 = next(t for t in north["trucks"] if t["name"] == "N1")
        assert n1["used_minutes"] == 70 and n1["loads"][0]["order_name"] == "Board"
        topsoil = next(s for s in north["stock"] if s["product"] == "screened_topsoil")
        assert topsoil["carried"] and topsoil["in_stock"]
        assert not next(s for s in north["stock"] if s["product"] == "compost")["carried"]


def order_payload(**overrides):
    payload = {
        "name": "Pat Customer",
        "phone": "555-0100",
        "contact_consent": True,
        "email": "pat@example.com",
        "delivery_address": "123 Main St, Denver",
        "zip_code": "80202",
        "items": [{"key": "screened_topsoil", "quantity": 10}],
        "preferred_date": delivery_day(7).isoformat(),
        "delivery_window": "morning",
        "placement_notes": "Driveway, left side",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestPublicEndpoints:
    def test_catalog(self):
        data = APIClient().get("/api/v1/intake/catalog/").data
        assert [p["key"] for p in data["products"]][:2] == ["screened_topsoil", "garden_blend"]
        assert data["delivery_base_fee"] == str(pricing.DELIVERY_BASE_FEE)
        assert data["delivery_weekdays"] == [0, 1, 2, 3, 4, 5]

    def test_estimate_routes_and_prices(self, network):
        r = APIClient().post(
            "/api/v1/intake/estimate/",
            {"items": [{"key": "screened_topsoil", "quantity": 10}], "zip_code": "80202", "preferred_date": delivery_day(7).isoformat()},
            format="json",
        )
        assert r.status_code == 200, r.data
        assert r.data["quote"]["total"] == "505.00"  # 10 x $42 + $85 delivery
        assert r.data["plan"]["status"] == "ok" and r.data["plan"]["city"] == "Denver"
        load = r.data["plan"]["loads"][0]
        assert load["yard_name"] == "North yard" and "truck" not in load and "truck_name" not in load

    def test_estimate_outside_and_special(self, network):
        client = APIClient()
        outside = client.post("/api/v1/intake/estimate/", {"items": [], "zip_code": "99999"}, format="json").data
        assert outside["quote"] is None and outside["plan"]["status"] == "outside_area"
        special = client.post("/api/v1/intake/estimate/", {"items": [{"key": "compost", "quantity": 3}], "zip_code": "80403"}, format="json").data
        assert special["plan"]["status"] == "special_request" and special["quote"] is None

    def test_estimate_validation(self):
        client = APIClient()
        r = client.post("/api/v1/intake/estimate/", {"items": [{"key": "fill_dirt", "quantity": 2}], "zip_code": "8020"}, format="json")
        assert r.status_code == 400
        assert "5-yard minimum" in str(r.data["items"]) and "zip_code" in r.data
        sunday = delivery_day(7)
        while sunday.weekday() != 6:
            sunday += timedelta(days=1)
        r = client.post("/api/v1/intake/estimate/", {"items": [], "preferred_date": sunday.isoformat()}, format="json")
        assert "Sundays" in str(r.data["preferred_date"])

    def test_order_books_loads(self, network, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            r = APIClient().post("/api/v1/intake/orders/", order_payload(), format="json")
        assert r.status_code == 201, r.data
        assert r.data["plan_status"] == "ok" and r.data["claim_token"]
        order = Order.objects.get()
        assert order.items == {"screened_topsoil": 10}
        assert order.estimated_total == Decimal("505.00") and order.coverage == "serve"
        assert [(l.truck.name, l.date) for l in order.loads.all()] == [("N1", order.preferred_date)]

    def test_order_requires_a_served_zip(self, network):
        client = APIClient()
        r = client.post("/api/v1/intake/orders/", order_payload(zip_code="99999"), format="json")
        assert r.status_code == 400 and "special request" in str(r.data["zip_code"])
        r = client.post("/api/v1/intake/orders/", order_payload(zip_code="80403"), format="json")
        assert r.status_code == 400 and "by special request" in str(r.data["zip_code"])

    def test_special_request_from_anywhere(self, network):
        r = APIClient().post(
            "/api/v1/intake/orders/",
            order_payload(request_type="callback", zip_code="99999", notes="Need 30 yards up a mountain", preferred_date=None),
            format="json",
        )
        assert r.status_code == 201, r.data
        order = Order.objects.get()
        assert order.coverage == "outside" and order.loads.count() == 0 and order.quote == {}

    def test_order_required_fields(self):
        r = APIClient().post("/api/v1/intake/orders/", {"name": "Pat"}, format="json")
        assert r.status_code == 400
        assert {"phone", "contact_consent", "items", "preferred_date", "delivery_address", "zip_code"} <= set(r.data)
        r = APIClient().post("/api/v1/intake/orders/", {"name": "Pat", "request_type": "callback"}, format="json")
        assert "notes" in r.data and "items" not in r.data
