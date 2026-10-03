"""Tests for table-based parts estimates and the CSV import/export commands."""

import io
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.intake import parts
from apps.intake.models import PartPriceExample, ServiceRequest

User = get_user_model()
VIN = "1HGCM82633A004352"
SEDAN = {"year": "2003", "make": "HONDA", "model": "Accord", "body": "Sedan/Saloon"}


@pytest.fixture(autouse=True)
def _setup(settings):
    cache.clear()
    settings.PARTS_ESTIMATE_ASYNC = False
    settings.TURNSTILE_SECRET_KEY = ""
    settings.INTAKE_NOTIFY_EMAILS = []
    with mock.patch.object(parts, "decode_vin", return_value=dict(SEDAN)):
        yield
    cache.clear()


def add(service, vehicle_type, price, make=""):
    return PartPriceExample.objects.create(
        service=service, vehicle_type=vehicle_type, price=Decimal(price), vehicle_make=make
    )


def payload(**overrides):
    data = {
        "name": "Pat",
        "phone": "555-0100",
        "contact_consent": True,
        "vin": VIN,
        "services": [{"key": "brake_pads", "quantity": 2}, {"key": "oil_change"}],
        "preferred_date": (timezone.localdate() + timedelta(days=20)).isoformat(),
    }
    data.update(overrides)
    return data


def submit(capture, client=None, **overrides):
    with capture(execute=True):
        return (client or APIClient()).post("/api/v1/intake/requests/", payload(**overrides), format="json")


class TestClassify:
    @pytest.mark.parametrize(
        "profile, expected",
        [
            ({"make": "BMW", "body": "Sport Utility Vehicle (SUV)/Multi-Purpose Vehicle (MPV)"}, "european"),
            ({"make": "FORD", "body": "Pickup"}, "truck"),
            ({"make": "HONDA", "body": "Sport Utility Vehicle (SUV)/Multi-Purpose Vehicle (MPV)", "gvwr": "Class 1D: 5,001 - 6,000 lb"}, "crossover"),
            ({"make": "CHEVROLET", "body": "Sport Utility Vehicle (SUV)/Multi-Purpose Vehicle (MPV)", "gvwr": "Class 2E: 6,001 - 7,000 lb"}, "suv"),
            ({"make": "HONDA", "body": "Minivan"}, "suv"),
            ({"make": "TOYOTA", "body": "Hatchback/Liftback/Notchback"}, "sedan"),
            # No body class (e.g. a failed NHTSA call): mixed-lineup makes stay unknown...
            ({"make": "TOYOTA"}, ""),
            ({"make": "FORD"}, ""),
            # ...but a handful of makes with an unambiguous lineup get a fallback default.
            ({"make": "RAM"}, "truck"),
            ({"make": "JEEP"}, "suv"),
            ({"make": "BUICK"}, "crossover"),
            # European still wins even with no body class at all.
            ({"make": "BMW"}, "european"),
        ],
    )
    def test_vehicle_types(self, profile, expected):
        assert parts.classify(profile) == expected


@pytest.mark.django_db
class TestEstimate:
    def test_min_median_max_times_quantity(self):
        for price in ("40", "50", "90"):
            add("brake_pads", "sedan", price)
        result = parts.estimate({"brake_pads": 2}, "sedan", "HONDA")
        line = result["services"][0]
        assert (line["low"], line["typical"], line["high"]) == ("80", "100", "180")
        assert line["sample_count"] == 3 and line["basis"] == {"make": "", "type": "sedan"}
        # Stored data is keys; labels are rendered at read time.
        assert parts.localize(result)["services"][0]["basis_label"] == "sedan / car"
        assert (result["low"], result["typical"], result["high"]) == ("80", "100", "180")

    def test_most_specific_match_wins(self):
        add("brake_pads", "sedan", "40")
        add("brake_pads", "suv", "70", make="HONDA")
        assert parts.estimate({"brake_pads": 1}, "sedan", "HONDA")["services"][0]["low"] == "70"
        add("brake_pads", "sedan", "55", make="HONDA")
        assert parts.estimate({"brake_pads": 1}, "sedan", "HONDA")["services"][0]["low"] == "55"
        # Another make falls back to the vehicle-type examples.
        assert parts.estimate({"brake_pads": 1}, "sedan", "TOYOTA")["services"][0]["low"] == "40"

    def test_jobs_without_examples_are_listed_as_missing(self):
        add("brake_pads", "sedan", "40")
        result = parts.estimate({"brake_pads": 1, "alternator": 1}, "sedan", "")
        assert [s["service_key"] for s in result["services"]] == ["brake_pads"]
        assert result["missing"] == ["alternator"]
        assert parts.localize(result)["missing"] == ["Alternator"]


@pytest.mark.django_db
class TestLivePreview:
    """The /estimate/ preview: a parts range from the chosen vehicle class alone, no VIN."""

    def estimate(self, **body):
        body.setdefault("services", [{"key": "brake_pads", "quantity": 2}, {"key": "oil_change"}])
        return APIClient().post("/api/v1/intake/estimate/", body, format="json")

    def test_no_vehicle_type_means_no_parts_preview(self):
        add("brake_pads", "sedan", "40")
        response = self.estimate()
        assert response.status_code == 200
        assert "parts_estimate" not in response.data

    def test_vehicle_type_alone_is_enough(self):
        add("brake_pads", "sedan", "40")
        add("brake_pads", "sedan", "60")
        add("oil_change", "sedan", "35")
        response = self.estimate(vehicle_type="sedan")
        estimate = response.data["parts_estimate"]
        assert estimate["status"] == "ready" and estimate["vehicle_type"] == "sedan"
        # Pads x2 axles (80-120) + oil (35), no VIN or make involved.
        assert (estimate["low"], estimate["typical"], estimate["high"]) == ("115", "135", "155")

    def test_unavailable_when_nothing_matches(self):
        add("alternator", "truck", "200")
        response = self.estimate(vehicle_type="sedan")
        estimate = response.data["parts_estimate"]
        assert estimate["status"] == "unavailable"
        assert set(estimate["missing"]) == {"Brake pads", "Oil & filter change"}

    def test_rejects_unknown_vehicle_type(self):
        assert self.estimate(vehicle_type="spaceship").status_code == 400


@pytest.mark.django_db
class TestRequests:
    def test_off_until_the_table_has_data(self, django_capture_on_commit_callbacks):
        response = submit(django_capture_on_commit_callbacks)
        assert response.data["parts_estimate_status"] is None
        assert ServiceRequest.objects.get().parts_estimate_status == ""

    def test_guest_sees_estimate_via_claim_token(self, django_capture_on_commit_callbacks):
        add("brake_pads", "sedan", "40")
        add("brake_pads", "sedan", "60")
        add("oil_change", "sedan", "35")
        response = submit(django_capture_on_commit_callbacks)
        assert response.data["parts_estimate_status"] == "pending"
        poll = APIClient().post(
            "/api/v1/intake/requests/parts-estimate/",
            {"claim_token": response.data["claim_token"]},
            format="json",
        )
        estimate = poll.data["parts_estimate"]
        assert estimate["status"] == "ready" and estimate["vehicle_type"] == "sedan"
        # Pads x2 axles (80-120) + oil (35).
        assert (estimate["low"], estimate["typical"], estimate["high"]) == ("115", "135", "155")
        assert estimate["vehicle_summary"] == "2003 Honda Accord"
        assert ServiceRequest.objects.get().vehicle_type == "sedan"

    def test_customers_own_vehicle_type_choice_wins_over_the_vin_decode(
        self, django_capture_on_commit_callbacks
    ):
        add("brake_pads", "crossover", "70")
        # The module-level fixture mocks the VIN decode to a sedan; the customer
        # picked crossover on the form before ever typing a VIN. Their answer sticks.
        response = submit(django_capture_on_commit_callbacks, vehicle_type="crossover")
        assert response.data["parts_estimate_status"] == "pending"
        assert ServiceRequest.objects.get().vehicle_type == "crossover"

    def test_guest_poll_rejects_bad_token(self):
        r = APIClient().post("/api/v1/intake/requests/parts-estimate/", {"claim_token": "nope"}, format="json")
        assert r.status_code == 404

    def test_unavailable_when_nothing_matches(self, django_capture_on_commit_callbacks):
        add("alternator", "truck", "200")
        submit(django_capture_on_commit_callbacks)
        assert ServiceRequest.objects.get().parts_estimate_status == "unavailable"

    def test_staff_vehicle_type_change_recalculates(self, django_capture_on_commit_callbacks):
        add("brake_pads", "sedan", "40")
        add("brake_pads", "truck", "90")
        submit(django_capture_on_commit_callbacks, services=[{"key": "brake_pads"}])
        req = ServiceRequest.objects.get()
        staff = User.objects.create_user(email="m@x.com", name="M", password="x", is_staff=True)
        client = APIClient()
        client.force_authenticate(staff)
        with django_capture_on_commit_callbacks(execute=True):
            r = client.patch(f"/api/v1/manage/requests/{req.id}/", {"vehicle_type": "truck"}, format="json")
        assert r.status_code == 200
        req.refresh_from_db()
        assert req.parts_estimate_result["low"] == "90"

    def test_recalculate_is_staff_only(self, django_capture_on_commit_callbacks):
        add("brake_pads", "sedan", "40")
        submit(django_capture_on_commit_callbacks)
        req = ServiceRequest.objects.get()
        add("brake_pads", "sedan", "80")
        customer = User.objects.create_user(email="c@x.com", name="C", password="x")
        staff = User.objects.create_user(email="m@x.com", name="M", password="x", is_staff=True)
        url = f"/api/v1/manage/requests/{req.id}/parts-estimate/"
        client = APIClient()
        client.force_authenticate(customer)
        assert client.post(url).status_code == 403
        client.force_authenticate(staff)
        assert client.post(url).data["parts_estimate"]["high"] == "160"  # 2 axles x $80

    def test_customer_sees_estimate_on_their_request(self, django_capture_on_commit_callbacks):
        add("brake_pads", "sedan", "40")
        customer = User.objects.create_user(email="c@x.com", name="C", password="x")
        client = APIClient()
        client.force_authenticate(customer)
        submit(django_capture_on_commit_callbacks, client=client)
        req = ServiceRequest.objects.get()
        assert client.get(f"/api/v1/garage/requests/{req.id}/").data["parts_estimate"]["status"] == "ready"

    def test_background_crash_marks_unavailable(self, django_capture_on_commit_callbacks):
        add("brake_pads", "sedan", "40")
        with mock.patch.object(parts, "estimate", side_effect=RuntimeError("boom")):
            submit(django_capture_on_commit_callbacks)
        assert ServiceRequest.objects.get().parts_estimate_status == "unavailable"


@pytest.mark.django_db
class TestImportExport:
    def write(self, tmp_path, text):
        path = tmp_path / "prices.csv"
        path.write_text(text)
        return str(path)

    def test_import_skips_blank_prices_and_normalizes(self, tmp_path):
        path = self.write(
            tmp_path,
            "service,vehicle_type,vehicle_make,part_brand,price,unit\n"
            "brake_pads,Sedan,toyota,Duralast Gold,$45.99,per axle\n"
            "brake_pads,suv,,,,per axle\n",
        )
        out = io.StringIO()
        call_command("import_part_prices", path, stdout=out)
        example = PartPriceExample.objects.get()
        assert example.vehicle_make == "TOYOTA" and example.vehicle_type == "sedan"
        assert example.price == Decimal("45.99")
        assert "skipped 1" in out.getvalue()

    def test_bad_rows_import_nothing(self, tmp_path):
        path = self.write(
            tmp_path,
            "service,vehicle_type,price\nbrake_pads,sedan,40\nengine_swap,sedan,10\nbrake_pads,boat,10\noil_change,sedan,abc\n",
        )
        with pytest.raises(CommandError) as exc:
            call_command("import_part_prices", path)
        assert "line 3" in str(exc.value) and "line 4" in str(exc.value) and "line 5" in str(exc.value)
        assert not PartPriceExample.objects.exists()

    def test_replace_and_round_trip(self, tmp_path):
        add("oil_change", "truck", "60")
        path = self.write(tmp_path, "service,vehicle_type,price\noil_change,sedan,35\n")
        call_command("import_part_prices", path, "--replace", stdout=io.StringIO())
        assert list(PartPriceExample.objects.values_list("vehicle_type", flat=True)) == ["sedan"]

        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            call_command("export_part_prices")
        exported = self.write(tmp_path, out.getvalue())
        call_command("import_part_prices", exported, "--replace", stdout=io.StringIO())
        assert PartPriceExample.objects.get().price == Decimal("35.00")

    def test_blank_template_imports_cleanly(self):
        template = Path(parts.__file__).parent / "data" / "part_prices_template.csv"
        out = io.StringIO()
        call_command("import_part_prices", str(template), stdout=out)
        assert PartPriceExample.objects.count() == 0
        assert "skipped 40" in out.getvalue()
