"""Tests for verified invoices and the live-update (polling) endpoints."""

from decimal import Decimal

import pytest
from django.core import mail
from django.core.cache import cache

from apps.intake.models import Invoice, RequestMessage, ServiceRequest
from apps.intake.test_accounts import client_for, make_user


@pytest.fixture(autouse=True)
def _setup(settings):
    cache.clear()
    settings.INTAKE_NOTIFY_EMAILS = ["owner@example.com"]
    settings.SITE_URL = "https://shop.example"
    yield
    cache.clear()


@pytest.fixture
def customer(db):
    return make_user("pat@example.com")


@pytest.fixture
def staff(db):
    return make_user("mech@example.com", staff=True)


@pytest.fixture
def booking(db, customer):
    return ServiceRequest.objects.create(
        name="Pat Customer",
        email="pat@example.com",
        customer=customer,
        services={"brake_pads": 1},
        is_emergency=True,
        language="es",
    )


def invoice_body(**overrides):
    body = {
        "services": [{"key": "brake_pads"}, {"key": "brake_rotors"}],
        "charge_rush_fee": False,
        "lines": [
            {"kind": "part", "description": "Akebono pads (RockAuto)", "quantity": "1", "unit_price": "48.10"},
            {"kind": "part", "description": "Rotors", "quantity": "2", "unit_price": "39.99"},
            {"kind": "shipping", "description": "RockAuto shipping", "quantity": "1", "unit_price": "12.50"},
        ],
        "note": "Front axle only.",
        "published": False,
        "notify_customer": False,
    }
    body.update(overrides)
    return body


def url(req, suffix=""):
    return f"/api/v1/manage/requests/{req.id}/invoice/{suffix}"


@pytest.mark.django_db
class TestStaffInvoice:
    def test_draft_starts_from_requested_jobs(self, staff, booking):
        data = client_for(staff).get(url(booking)).json()
        assert data["exists"] is False
        assert [s["key"] for s in data["services"]] == ["brake_pads"]
        # The request was a same-week job, so the draft keeps the rush fee.
        assert data["charge_rush_fee"] is True
        assert data["labor"]["emergency_fee"] == "75.00"

    def test_preview_reprices_jobs_with_bundles_and_sums_lines(self, staff, booking):
        response = client_for(staff).post(url(booking, "preview/"), invoice_body(), format="json")
        assert response.status_code == 200
        data = response.json()
        # Pads 55 + rotors 70 - bundle 40 + service call 45, no rush fee.
        assert data["totals"]["jobs"] == "130.00"
        assert [d["key"] for d in data["labor"]["discounts"]] == ["pads_rotors"]
        assert data["totals"]["parts"] == "128.08"
        assert data["totals"]["shipping"] == "12.50"
        assert data["totals"]["total"] == "270.58"
        assert data["lines"][1] == {
            "kind": "part", "description": "Rotors", "quantity": "2", "unit_price": "39.99", "amount": "79.98",
        }
        assert not Invoice.objects.exists()

    def test_save_draft_is_hidden_from_customer(self, staff, customer, booking):
        response = client_for(staff).put(url(booking), invoice_body(), format="json")
        assert response.status_code == 200
        assert response.json()["published_at"] is None
        booking.refresh_from_db()
        assert booking.invoice.total == Decimal("270.58")
        assert booking.final_total is None
        detail = client_for(customer).get(f"/api/v1/garage/requests/{booking.id}/").json()
        assert detail["invoice"] is None
        # Staff see their draft on the request.
        staff_detail = client_for(staff).get(f"/api/v1/manage/requests/{booking.id}/").json()
        assert staff_detail["invoice"]["totals"]["total"] == "270.58"

    def test_publish_shows_invoice_sets_final_total_and_emails(
        self, staff, customer, booking, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = client_for(staff).put(
                url(booking), invoice_body(published=True, notify_customer=True), format="json"
            )
        assert response.json()["published_at"]
        booking.refresh_from_db()
        assert booking.final_total == Decimal("270.58")

        detail = client_for(customer).get(f"/api/v1/garage/requests/{booking.id}/", HTTP_ACCEPT_LANGUAGE="es").json()
        invoice = detail["invoice"]
        assert invoice["totals"]["total"] == "270.58"
        # Labor names follow the reader's language; staff-typed lines don't change.
        assert invoice["labor"]["line_items"][0]["name"] == "Pastillas de freno"
        assert invoice["lines"][0]["description"] == "Akebono pads (RockAuto)"

        [email] = mail.outbox
        assert email.to == ["pat@example.com"]
        assert email.subject == f"Tu factura de la solicitud #{booking.id}"
        assert "Pieza: Rotors x2: $79.98" in email.body
        assert "Envío: RockAuto shipping: $12.50" in email.body
        assert "Total: $270.58" in email.body

    def test_editing_a_published_invoice_does_not_email_again(
        self, staff, booking, django_capture_on_commit_callbacks
    ):
        client = client_for(staff)
        with django_capture_on_commit_callbacks(execute=True):
            client.put(url(booking), invoice_body(published=True, notify_customer=True), format="json")
            first_published = booking.__class__.objects.get(pk=booking.pk).invoice.published_at
            client.put(
                url(booking),
                invoice_body(published=True, notify_customer=True, lines=[]),
                format="json",
            )
        assert len(mail.outbox) == 1
        booking.refresh_from_db()
        assert booking.invoice.published_at == first_published
        assert booking.final_total == Decimal("130.00")
        assert booking.invoice.lines.count() == 0

    def test_published_invoice_overrides_manual_final_total(self, staff, booking):
        client = client_for(staff)
        client.put(url(booking), invoice_body(published=True), format="json")
        client.patch(f"/api/v1/manage/requests/{booking.id}/", {"final_total": "1.00"}, format="json")
        booking.refresh_from_db()
        assert booking.final_total == Decimal("270.58")

    def test_unpublish_and_delete_clear_final_total(self, staff, customer, booking):
        client = client_for(staff)
        client.put(url(booking), invoice_body(published=True), format="json")
        client.put(url(booking), invoice_body(published=False), format="json")
        booking.refresh_from_db()
        assert booking.final_total is None
        assert client_for(customer).get(f"/api/v1/garage/requests/{booking.id}/").json()["invoice"] is None

        client.put(url(booking), invoice_body(published=True), format="json")
        assert client.delete(url(booking)).status_code == 204
        booking.refresh_from_db()
        assert booking.final_total is None
        assert not Invoice.objects.exists()

    def test_callback_request_can_get_jobs_added(self, staff, db):
        req = ServiceRequest.objects.create(name="Sam", request_type=ServiceRequest.RequestType.CALLBACK)
        client = client_for(staff)
        assert client.get(url(req)).json()["services"] == []
        response = client.put(url(req), invoice_body(services=[{"key": "oil_change"}], lines=[]), format="json")
        assert response.json()["totals"]["total"] == "75.00"

    def test_rush_fee_is_staff_choice(self, staff, booking):
        data = client_for(staff).post(
            url(booking, "preview/"), invoice_body(charge_rush_fee=True, lines=[]), format="json"
        ).json()
        assert data["labor"]["emergency_fee"] == "75.00"
        assert data["totals"]["total"] == "205.00"

    @pytest.mark.parametrize(
        "line, field",
        [
            ({"kind": "part", "description": "Pads", "quantity": "1", "unit_price": "-5"}, "unit_price"),
            ({"kind": "part", "description": "Pads", "quantity": "0", "unit_price": "5"}, "quantity"),
            ({"kind": "part", "description": "", "quantity": "1", "unit_price": "5"}, "description"),
            ({"kind": "bribe", "description": "x", "quantity": "1", "unit_price": "5"}, "kind"),
        ],
    )
    def test_line_validation(self, staff, booking, line, field):
        response = client_for(staff).put(url(booking), invoice_body(lines=[line]), format="json")
        assert response.status_code == 400
        assert field in response.json()["lines"]["0"]

    def test_discount_adjustment_can_be_negative(self, staff, booking):
        line = {"kind": "adjustment", "description": "Repeat customer", "quantity": "1", "unit_price": "-10"}
        data = client_for(staff).post(url(booking, "preview/"), invoice_body(lines=[line]), format="json").json()
        assert data["totals"]["adjustments"] == "-10.00"
        assert data["totals"]["total"] == "120.00"

    def test_customers_cannot_use_staff_invoice_endpoints(self, customer, booking):
        client = client_for(customer)
        assert client.get(url(booking)).status_code == 403
        assert client.put(url(booking), invoice_body(), format="json").status_code == 403
        assert client.post(url(booking, "preview/"), invoice_body(), format="json").status_code == 403


@pytest.mark.django_db
class TestLiveUpdates:
    def test_customer_gets_new_messages_after_id_and_marks_them_read(self, customer, booking):
        old = RequestMessage.objects.create(request=booking, body="Earlier", from_staff=True)
        new = RequestMessage.objects.create(request=booking, body="Parts are in", from_staff=True)
        response = client_for(customer).get(
            f"/api/v1/garage/requests/{booking.id}/updates/", {"after": old.id}
        )
        assert response.status_code == 200
        data = response.json()
        assert [m["body"] for m in data["messages"]] == ["Parts are in"]
        assert data["updated_at"]
        new.refresh_from_db()
        assert new.read_at is not None

    def test_updated_at_moves_when_staff_change_the_request(self, staff, customer, booking):
        poll = f"/api/v1/garage/requests/{booking.id}/updates/"
        before = client_for(customer).get(poll).json()["updated_at"]
        client_for(staff).put(url(booking), invoice_body(published=True), format="json")
        assert client_for(customer).get(poll).json()["updated_at"] != before

    def test_customer_cannot_poll_someone_elses_request(self, booking):
        other = make_user("other@example.com")
        assert client_for(other).get(f"/api/v1/garage/requests/{booking.id}/updates/").status_code == 404

    def test_staff_poll_marks_customer_messages_read(self, staff, booking):
        message = RequestMessage.objects.create(request=booking, body="Question", from_staff=False)
        data = client_for(staff).get(f"/api/v1/manage/requests/{booking.id}/updates/").json()
        assert [m["body"] for m in data["messages"]] == ["Question"]
        message.refresh_from_db()
        assert message.read_at is not None

    def test_bad_after_value_returns_everything(self, customer, booking):
        RequestMessage.objects.create(request=booking, body="Hi", from_staff=True)
        data = client_for(customer).get(
            f"/api/v1/garage/requests/{booking.id}/updates/", {"after": "nope"}
        ).json()
        assert len(data["messages"]) == 1
