"""Tests for the intake app: pricing rules and the public endpoints."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.intake import pricing
from apps.intake.models import ServiceRequest

VALID_VIN = "1HGCM82633A004352"
TODAY = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


def in_days(days: int) -> str:
    return (timezone.localdate() + timedelta(days=days)).isoformat()


class TestPricing:
    def test_rates_meet_target_after_overhead(self):
        assert pricing.LABOR_RATE >= pricing.TARGET_HOURLY_RATE
        # Driving is covered by the service call fee, at the target rate.
        assert pricing.SERVICE_CALL_FEE >= (
            pricing.TRAVEL_HOURS_PER_VISIT * pricing.TARGET_HOURLY_RATE
        )
        for service in pricing.SERVICES:
            if not service.quote_required:
                assert service.price >= service.labor_hours * pricing.LABOR_RATE
                assert service.price % 5 == 0

    def test_single_service(self):
        quote = pricing.estimate({"oil_change": 1}, TODAY + timedelta(days=14), TODAY)
        oil = pricing.SERVICES_BY_KEY["oil_change"].price
        assert Decimal(quote["total"]) == oil + pricing.SERVICE_CALL_FEE
        assert quote["discounts"] == []
        assert quote["emergency_fee"] == "0.00"
        assert quote["scheduling"]["short_notice"] is False

    def test_pads_and_rotors_bundle_per_axle(self):
        quote = pricing.estimate({"brake_pads": 2, "brake_rotors": 1}, None, TODAY)
        assert [d["key"] for d in quote["discounts"]] == ["pads_rotors"]
        assert quote["discounts"][0]["units"] == 1
        bundle = pricing.BUNDLES[0]
        assert Decimal(quote["discount_total"]) == bundle.discount_per_unit

    def test_brakes_and_suspension_bundle(self):
        quote = pricing.estimate(
            {"brake_pads": 1, "brake_rotors": 1, "suspension": 1}, None, TODAY
        )
        assert {d["key"] for d in quote["discounts"]} == {"pads_rotors", "brakes_suspension"}
        assert Decimal(quote["total"]) < (
            Decimal(quote["subtotal"]) + pricing.SERVICE_CALL_FEE
        )
        # Bundled jobs still clear the target rate on the hours actually worked.
        labor = Decimal(quote["subtotal"]) - Decimal(quote["discount_total"])
        assert labor >= Decimal(quote["labor_hours"]) * pricing.TARGET_HOURLY_RATE

    def test_addons_free_on_long_jobs(self):
        quote = pricing.estimate(
            {"brake_pads": 2, "brake_rotors": 2, "oil_change": 1, "air_filter": 1}, None, TODAY
        )
        keys = [d["key"] for d in quote["discounts"]]
        assert "free_oil_change" in keys and "free_air_filter" in keys
        # Labor is just the bundled brake job; the add-ons cost nothing.
        brakes_only = pricing.estimate({"brake_pads": 2, "brake_rotors": 2}, None, TODAY)
        assert quote["total"] == brakes_only["total"]

    def test_addons_charged_on_short_jobs(self):
        # One axle of pads is 1 hour: under the 2-hour bar.
        quote = pricing.estimate({"brake_pads": 1, "oil_change": 1}, None, TODAY)
        assert quote["discounts"] == []

    def test_addon_hours_do_not_count_toward_the_bar(self):
        # 1.75 hr of other work + 0.5 hr oil change: still not free.
        quote = pricing.estimate({"brake_pads": 1, "brake_rotors": 1, "oil_change": 1}, None, TODAY)
        assert "free_oil_change" not in [d["key"] for d in quote["discounts"]]

    def test_volume_rate_past_threshold(self):
        quote = pricing.estimate({"brake_pads": 2, "brake_rotors": 2, "suspension": 2}, None, TODAY)
        volume = next(d for d in quote["discounts"] if d["key"] == "volume_rate")
        before_volume = Decimal(quote["subtotal"]) - (
            Decimal(quote["discount_total"]) - Decimal(volume["amount"])
        )
        over = before_volume - pricing.VOLUME_THRESHOLD
        # Labor past the threshold bills at roughly VOLUME_RATE (rounded in the customer's favor).
        expected = over * (pricing.LABOR_RATE - pricing.VOLUME_RATE) / pricing.LABOR_RATE
        assert expected - 5 < Decimal(volume["amount"]) <= expected
        labor = Decimal(quote["subtotal"]) - Decimal(quote["discount_total"])
        assert labor >= pricing.VOLUME_THRESHOLD

    def test_no_volume_rate_at_or_under_threshold(self):
        quote = pricing.estimate({"brake_pads": 1, "brake_rotors": 1, "suspension": 1}, None, TODAY)
        assert "volume_rate" not in [d["key"] for d in quote["discounts"]]

    def test_catalog_lists_deals(self):
        assert [d["key"] for d in pricing.catalog()["deals"]] == ["free_addons", "volume_rate"]

    def test_same_week_is_emergency(self):
        quote = pricing.estimate({"oil_change": 1}, TODAY + timedelta(days=3), TODAY)
        assert quote["scheduling"]["is_emergency"] is True
        assert Decimal(quote["emergency_fee"]) == pricing.EMERGENCY_FEE

    def test_inside_lead_time_flags_short_notice_without_fee(self):
        quote = pricing.estimate({"oil_change": 1}, TODAY + timedelta(days=10), TODAY)
        assert quote["scheduling"]["is_emergency"] is False
        assert quote["scheduling"]["short_notice"] is True
        assert quote["emergency_fee"] == "0.00"

    def test_other_needs_custom_quote(self):
        quote = pricing.estimate({"other": 1}, None, TODAY)
        assert quote["needs_custom_quote"] is True
        assert quote["line_items"][0]["amount"] == "0.00"


@pytest.mark.django_db
class TestIntakeAPI:
    def test_catalog_is_public(self, api_client):
        response = api_client.get("/api/v1/intake/catalog/")
        assert response.status_code == 200
        keys = [s["key"] for s in response.data["services"]]
        assert "brake_pads" in keys and "other" in keys
        assert response.data["booking_lead_days"] == 14

    def test_public_endpoints_ignore_stale_tokens(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        assert api_client.get("/api/v1/intake/catalog/").status_code == 200

    def test_estimate(self, api_client):
        response = api_client.post(
            "/api/v1/intake/estimate/",
            {
                "services": [{"key": "brake_pads", "quantity": 1}, {"key": "brake_rotors"}],
                "preferred_date": in_days(2),
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["scheduling"]["is_emergency"] is True
        assert response.data["discounts"][0]["key"] == "pads_rotors"

    def test_estimate_rejects_unknown_service(self, api_client):
        response = api_client.post(
            "/api/v1/intake/estimate/", {"services": [{"key": "engine_swap"}]}, format="json"
        )
        assert response.status_code == 400

    def test_create_booking_reprices_on_server(self, api_client):
        response = api_client.post(
            "/api/v1/intake/requests/",
            {
                "name": "Pat Customer",
                "phone": "555-0100",
                "vin": "1hgcm82633a004352",
                "services": [{"key": "oil_change"}, {"key": "air_filter"}],
                "preferred_date": in_days(20),
                # Client-supplied totals are ignored.
                "estimated_total": "1.00",
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        obj = ServiceRequest.objects.get()
        assert obj.vin == VALID_VIN
        assert obj.services == {"oil_change": 1, "air_filter": 1}
        expected = (
            pricing.SERVICES_BY_KEY["oil_change"].price
            + pricing.SERVICES_BY_KEY["air_filter"].price
            + pricing.SERVICE_CALL_FEE
        )
        assert obj.estimated_total == expected
        assert obj.is_emergency is False

    def test_booking_requires_vin_services_and_date(self, api_client):
        response = api_client.post(
            "/api/v1/intake/requests/",
            {"name": "Pat", "email": "pat@example.com"},
            format="json",
        )
        assert response.status_code == 400
        assert {"vin", "services", "preferred_date"} <= set(response.data)

    @pytest.mark.parametrize("vin", ["1HGCM82633A00435", "1HGCM82633A00435O"])
    def test_rejects_bad_vin(self, api_client, vin):
        response = api_client.post(
            "/api/v1/intake/requests/",
            {
                "name": "Pat",
                "phone": "555-0100",
                "vin": vin,
                "services": [{"key": "oil_change"}],
                "preferred_date": in_days(20),
            },
            format="json",
        )
        assert response.status_code == 400
        assert "vin" in response.data

    def test_other_requires_description(self, api_client):
        response = api_client.post(
            "/api/v1/intake/requests/",
            {
                "name": "Pat",
                "phone": "555-0100",
                "vin": VALID_VIN,
                "services": [{"key": "other"}],
                "preferred_date": in_days(20),
            },
            format="json",
        )
        assert response.status_code == 400
        assert "other_description" in response.data

    def test_rejects_past_date(self, api_client):
        response = api_client.post(
            "/api/v1/intake/estimate/",
            {"services": [{"key": "oil_change"}], "preferred_date": in_days(-1)},
            format="json",
        )
        assert response.status_code == 400

    def test_callback_request_needs_only_contact_and_note(self, api_client):
        response = api_client.post(
            "/api/v1/intake/requests/",
            {
                "request_type": "callback",
                "name": "Pat",
                "email": "pat@example.com",
                "notes": "Car makes a grinding noise, can you call me?",
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        obj = ServiceRequest.objects.get()
        assert obj.request_type == ServiceRequest.RequestType.CALLBACK
        assert obj.estimate == {}

    def test_requires_a_way_to_contact(self, api_client):
        response = api_client.post(
            "/api/v1/intake/requests/",
            {"request_type": "callback", "name": "Pat", "notes": "Call me"},
            format="json",
        )
        assert response.status_code == 400
        assert "phone" in response.data

    def test_submissions_are_throttled(self, api_client):
        payload = {
            "request_type": "callback",
            "name": "Pat",
            "phone": "555-0100",
            "notes": "Call me",
        }
        codes = [
            api_client.post("/api/v1/intake/requests/", payload, format="json").status_code
            for _ in range(11)
        ]
        assert codes[:10] == [201] * 10
        assert codes[10] == 429
