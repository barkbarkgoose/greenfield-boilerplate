"""Tests for customer garages, the staff dashboard API, emails and captcha."""

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.intake.models import RequestMessage, ServiceRequest, Vehicle
from apps.organizations.models import Organization

User = get_user_model()
VIN = "1HGCM82633A004352"
PASSWORD = "ValidPassword123!"


@pytest.fixture(autouse=True)
def _setup(settings):
    cache.clear()
    settings.INTAKE_NOTIFY_EMAILS = ["owner@example.com"]
    settings.SITE_URL = "https://shop.example"
    settings.TURNSTILE_SECRET_KEY = ""
    yield
    cache.clear()


def make_user(email, staff=False):
    org = Organization.objects.create(name=email)
    return User.objects.create_user(
        email=email, name=email.split("@")[0].title(), password=PASSWORD,
        organization=org, is_staff=staff,
    )


@pytest.fixture
def customer(db):
    return make_user("pat@example.com")


@pytest.fixture
def staff(db):
    return make_user("mech@example.com", staff=True)


def client_for(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def booking_payload(**overrides):
    payload = {
        "name": "Pat Customer",
        "phone": "555-0100",
        "email": "pat@example.com",
        "vin": VIN,
        "vehicle_year": "2003",
        "vehicle_make": "HONDA",
        "vehicle_model": "Accord",
        "services": [{"key": "oil_change"}],
        "preferred_date": (timezone.localdate() + timedelta(days=20)).isoformat(),
    }
    payload.update(overrides)
    return payload


def submit(client, capture, **overrides):
    with capture(execute=True):
        return client.post("/api/v1/intake/requests/", booking_payload(**overrides), format="json")


@pytest.mark.django_db
class TestSubmissionAndEmail:
    def test_guest_gets_claim_token_and_two_emails(self, django_capture_on_commit_callbacks):
        response = submit(client_for(), django_capture_on_commit_callbacks)
        assert response.status_code == 201
        token = response.data["claim_token"]
        assert token
        req = ServiceRequest.objects.get()
        assert req.customer is None and req.claim_token_hash and req.claim_token_hash != token

        assert len(mail.outbox) == 2
        owner, customer_mail = mail.outbox
        assert owner.to == ["owner@example.com"]
        assert "Pat Customer" in owner.subject
        assert f"/dashboard/requests/{req.id}" in owner.body
        assert owner.reply_to == ["pat@example.com"]
        assert customer_mail.to == ["pat@example.com"]
        assert f"https://shop.example/claim/{token}" in customer_mail.body
        assert "Estimated total" in customer_mail.body
        assert "zero markup" in customer_mail.body

    def test_emergency_flag_in_owner_subject(self, django_capture_on_commit_callbacks):
        submit(
            client_for(),
            django_capture_on_commit_callbacks,
            preferred_date=(timezone.localdate() + timedelta(days=2)).isoformat(),
        )
        assert "EMERGENCY" in mail.outbox[0].subject

    def test_no_customer_email_without_address(self, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks, email="")
        assert [m.to for m in mail.outbox] == [["owner@example.com"]]

    def test_signed_in_booking_files_to_garage(self, customer, django_capture_on_commit_callbacks):
        response = submit(client_for(customer), django_capture_on_commit_callbacks)
        assert response.status_code == 201
        assert response.data["claim_token"] is None
        req = ServiceRequest.objects.get()
        assert req.customer == customer
        assert req.vehicle.vin == VIN and req.vehicle.make == "HONDA"
        # A second booking for the same car reuses the vehicle.
        submit(client_for(customer), django_capture_on_commit_callbacks)
        assert Vehicle.objects.count() == 1
        assert "/account/requests/" in mail.outbox[1].body

    def test_stale_token_still_books_as_guest(self, django_capture_on_commit_callbacks):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer stale")
        assert submit(client, django_capture_on_commit_callbacks).status_code == 201


@pytest.mark.django_db
class TestSpamProtection:
    def test_honeypot_rejects(self, django_capture_on_commit_callbacks):
        response = submit(client_for(), django_capture_on_commit_callbacks, website="http://spam")
        assert response.status_code == 400
        assert not ServiceRequest.objects.exists()

    def test_captcha_required_when_configured(self, settings, django_capture_on_commit_callbacks):
        settings.TURNSTILE_SECRET_KEY = "secret"
        assert submit(client_for(), django_capture_on_commit_callbacks).status_code == 400

        with mock.patch("apps.intake.captcha.verify_turnstile", return_value=False):
            bad = submit(client_for(), django_capture_on_commit_callbacks, captcha_token="x")
        assert bad.status_code == 400 and "captcha_token" in bad.data

        with mock.patch("apps.intake.captcha.verify_turnstile", return_value=True) as verify:
            ok = submit(client_for(), django_capture_on_commit_callbacks, captcha_token="good")
        assert ok.status_code == 201
        assert verify.call_args.args[0] == "good"

    def test_signed_in_customers_skip_captcha(self, settings, customer, django_capture_on_commit_callbacks):
        settings.TURNSTILE_SECRET_KEY = "secret"
        assert submit(client_for(customer), django_capture_on_commit_callbacks).status_code == 201


@pytest.mark.django_db
class TestGarage:
    def test_claim_links_request_and_vehicle_once(self, customer, django_capture_on_commit_callbacks):
        token = submit(client_for(), django_capture_on_commit_callbacks).data["claim_token"]
        client = client_for(customer)
        response = client.post("/api/v1/garage/claim/", {"token": token}, format="json")
        assert response.status_code == 200
        req = ServiceRequest.objects.get()
        assert req.customer == customer and req.vehicle.vin == VIN
        assert req.claim_token_hash == ""
        other = make_user("other@example.com")
        again = client_for(other).post("/api/v1/garage/claim/", {"token": token}, format="json")
        assert again.status_code == 404

    def test_claim_requires_login(self):
        assert APIClient().post("/api/v1/garage/claim/", {"token": "x"}).status_code == 401

    def test_vehicle_history_and_isolation(self, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        submit(client_for(customer), django_capture_on_commit_callbacks, services=[{"key": "air_filter"}])
        vehicles = client_for(customer).get("/api/v1/garage/vehicles/").data
        assert len(vehicles) == 1 and len(vehicles[0]["history"]) == 2

        other = make_user("other@example.com")
        req = ServiceRequest.objects.first()
        assert client_for(other).get(f"/api/v1/garage/requests/{req.id}/").status_code == 404
        assert client_for(other).get("/api/v1/garage/requests/").data == []

    def test_customer_detail_hides_internal_notes(self, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        req = ServiceRequest.objects.get()
        req.internal_notes = "charge extra"
        req.save()
        data = client_for(customer).get(f"/api/v1/garage/requests/{req.id}/").data
        assert "internal_notes" not in data
        assert data["services"] == [{"key": "oil_change", "name": "Oil & filter change", "quantity": 1}]

    def test_nickname_is_the_only_editable_vehicle_field(self, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        vehicle = Vehicle.objects.get()
        response = client_for(customer).patch(
            f"/api/v1/garage/vehicles/{vehicle.id}/", {"nickname": "Daily", "vin": "X"}, format="json"
        )
        assert response.status_code == 200
        vehicle.refresh_from_db()
        assert vehicle.nickname == "Daily" and vehicle.vin == VIN

    def test_message_thread_and_unread(self, customer, staff, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        req = ServiceRequest.objects.get()
        mail.outbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            r = client_for(customer).post(
                f"/api/v1/garage/requests/{req.id}/messages/", {"body": "Can you do Saturday?"}, format="json"
            )
        assert r.status_code == 201
        assert mail.outbox[-1].to == ["owner@example.com"]
        assert "Can you do Saturday?" in mail.outbox[-1].body

        listing = client_for(staff).get("/api/v1/manage/requests/?unread=1").data
        assert listing["results"][0]["unread_count"] == 1
        client_for(staff).get(f"/api/v1/manage/requests/{req.id}/")
        assert client_for(staff).get("/api/v1/manage/requests/?unread=1").data["count"] == 0

        with django_capture_on_commit_callbacks(execute=True):
            client_for(staff).post(
                f"/api/v1/manage/requests/{req.id}/messages/", {"body": "Saturday works."}, format="json"
            )
        assert mail.outbox[-1].to == ["pat@example.com"]
        mine = client_for(customer).get("/api/v1/garage/requests/").data
        assert mine[0]["unread_count"] == 1
        detail = client_for(customer).get(f"/api/v1/garage/requests/{req.id}/").data
        assert [m["from_staff"] for m in detail["messages"]] == [False, True]
        assert RequestMessage.objects.filter(read_at__isnull=True).count() == 0

    def test_blank_message_rejected(self, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        req = ServiceRequest.objects.get()
        r = client_for(customer).post(f"/api/v1/garage/requests/{req.id}/messages/", {"body": "  "}, format="json")
        assert r.status_code == 400


@pytest.mark.django_db
class TestStaffDashboard:
    def test_permissions(self, customer):
        assert APIClient().get("/api/v1/manage/requests/").status_code == 401
        assert client_for(customer).get("/api/v1/manage/requests/").status_code == 403
        assert client_for(customer).get("/api/v1/manage/summary/").status_code == 403

    def test_list_filters_and_summary(self, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        submit(client_for(), django_capture_on_commit_callbacks, name="Sam Other", vin="2HGCM82633A004352")
        ServiceRequest.objects.filter(name="Sam Other").update(status="contacted")
        client = client_for(staff)
        assert client.get("/api/v1/manage/requests/?status=new").data["count"] == 1
        found = client.get("/api/v1/manage/requests/?q=sam").data["results"]
        assert [r["name"] for r in found] == ["Sam Other"]
        summary = client.get("/api/v1/manage/summary/").data
        assert summary["status_counts"]["new"] == 1 and summary["status_counts"]["contacted"] == 1
        assert summary["new_this_week"] == 2

    def test_schedule_requires_time_and_notifies(self, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        req = ServiceRequest.objects.get()
        mail.outbox.clear()
        client = client_for(staff)
        url = f"/api/v1/manage/requests/{req.id}/"
        assert client.patch(url, {"status": "scheduled"}, format="json").status_code == 400

        when = (timezone.now() + timedelta(days=14)).replace(microsecond=0)
        with django_capture_on_commit_callbacks(execute=True):
            r = client.patch(
                url,
                {"status": "scheduled", "scheduled_for": when.isoformat(), "internal_notes": "bring jack", "notify_customer": True},
                format="json",
            )
        assert r.status_code == 200, r.data
        assert r.data["internal_notes"] == "bring jack"
        assert mail.outbox[-1].to == ["pat@example.com"]
        assert "Appointment:" in mail.outbox[-1].body

        # Saving without a change, or without notify, sends nothing.
        with django_capture_on_commit_callbacks(execute=True):
            client.patch(url, {"internal_notes": "x", "notify_customer": True}, format="json")
            client.patch(url, {"status": "completed", "final_total": "80.00"}, format="json")
        assert len(mail.outbox) == 1
        req.refresh_from_db()
        assert req.completed_on == timezone.localdate()

    def test_staff_cannot_rewrite_customer_data(self, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        req = ServiceRequest.objects.get()
        client_for(staff).patch(
            f"/api/v1/manage/requests/{req.id}/", {"estimated_total": "1.00", "name": "X"}, format="json"
        )
        req.refresh_from_db()
        assert req.name == "Pat Customer" and str(req.estimated_total) != "1.00"


@pytest.mark.django_db
class TestCustomerSignup:
    def test_register_without_organization(self):
        r = APIClient().post(
            "/api/v1/auth/register/",
            {"email": "new@example.com", "name": "New Person", "password": PASSWORD},
            format="json",
        )
        assert r.status_code == 201, r.data
        assert r.data["is_staff"] is False

    def test_login_reports_staff(self, staff):
        r = APIClient().post("/api/v1/auth/login/", {"email": staff.email, "password": PASSWORD}, format="json")
        assert r.data["user"]["is_staff"] is True
