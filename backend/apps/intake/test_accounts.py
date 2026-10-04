"""Tests for customer accounts, the staff dashboard and dispatch API, emails and captcha."""

from datetime import timedelta
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient

from apps.intake.conftest import delivery_day
from apps.intake.models import Order, OrderMessage, TruckDayOff, YardStock

User = get_user_model()
PASSWORD = "ValidPassword123!"


def make_user(email, staff=False):
    return User.objects.create_user(
        email=email, name=email.split("@")[0].title(), password=PASSWORD, is_staff=staff,
    )


@pytest.fixture
def customer(db):
    return make_user("pat@example.com")


@pytest.fixture
def staff(db):
    return make_user("dispatch@example.com", staff=True)


def client_for(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


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


def submit(client, capture, **overrides):
    with capture(execute=True):
        return client.post("/api/v1/intake/orders/", order_payload(**overrides), format="json")


@pytest.mark.django_db
class TestSubmissionAndEmail:
    def test_guest_gets_claim_token_and_two_emails(self, network, django_capture_on_commit_callbacks):
        response = submit(client_for(), django_capture_on_commit_callbacks)
        assert response.status_code == 201
        token = response.data["claim_token"]
        order = Order.objects.get()
        assert order.customer is None and order.claim_token_hash and order.claim_token_hash != token

        owner, customer_mail = mail.outbox
        assert owner.to == ["owner@example.com"] and "Pat Customer" in owner.subject
        assert f"/dashboard/orders/{order.id}" in owner.body
        assert "10 yd screened_topsoil from North yard on N1 (12.0 mi)" in owner.body
        assert "Where to dump it:\nDriveway, left side" in owner.body
        assert owner.reply_to == ["pat@example.com"]
        assert customer_mail.to == ["pat@example.com"]
        assert f"https://shop.example/claim/{token}" in customer_mail.body
        assert "Screened topsoil: 10 yd x $42.00 = $420.00" in customer_mail.body
        assert "Delivery, 10 yd screened topsoil (12.0 mi): $85.00" in customer_mail.body
        assert "Estimated total: $505.00" in customer_mail.body
        assert "(morning)" in customer_mail.body

    def test_flags_in_owner_subject(self, network, django_capture_on_commit_callbacks):
        for truck in network.trucks.values():
            TruckDayOff.objects.create(truck=truck, date=delivery_day(7))
        submit(client_for(), django_capture_on_commit_callbacks)
        assert "[NEEDS DISPATCH]" in mail.outbox[0].subject
        assert Order.objects.get().plan_status == "no_capacity"

    def test_rush_flag(self, network, django_capture_on_commit_callbacks):
        # Today, or tomorrow when today is Sunday: always inside the rush window.
        submit(client_for(), django_capture_on_commit_callbacks, preferred_date=delivery_day(0).isoformat())
        order = Order.objects.get()
        assert order.is_rush and "[RUSH]" in mail.outbox[0].subject
        assert order.quote["rush_fee"] != "0.00"

    def test_no_customer_email_without_address(self, network, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks, email="")
        assert [m.to for m in mail.outbox] == [["owner@example.com"]]

    def test_signed_in_order_files_to_account(self, network, customer, django_capture_on_commit_callbacks):
        response = submit(client_for(customer), django_capture_on_commit_callbacks)
        assert response.status_code == 201 and response.data["claim_token"] is None
        assert Order.objects.get().customer == customer
        assert "/account/orders/" in mail.outbox[1].body

    def test_stale_token_still_orders_as_guest(self, network, django_capture_on_commit_callbacks):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer stale")
        assert submit(client, django_capture_on_commit_callbacks).status_code == 201


@pytest.mark.django_db
class TestSpamProtection:
    def test_honeypot_rejects(self, network, django_capture_on_commit_callbacks):
        response = submit(client_for(), django_capture_on_commit_callbacks, website="http://spam")
        assert response.status_code == 400
        assert not Order.objects.exists()

    def test_captcha_required_when_configured(self, network, settings, django_capture_on_commit_callbacks):
        settings.TURNSTILE_SECRET_KEY = "secret"
        assert submit(client_for(), django_capture_on_commit_callbacks).status_code == 400

        with mock.patch("apps.intake.captcha.verify_turnstile", return_value=False):
            bad = submit(client_for(), django_capture_on_commit_callbacks, captcha_token="x")
        assert bad.status_code == 400 and "captcha_token" in bad.data

        with mock.patch("apps.intake.captcha.verify_turnstile", return_value=True) as verify:
            ok = submit(client_for(), django_capture_on_commit_callbacks, captcha_token="good")
        assert ok.status_code == 201
        assert verify.call_args.args[0] == "good"

    def test_signed_in_customers_skip_captcha(self, network, settings, customer, django_capture_on_commit_callbacks):
        settings.TURNSTILE_SECRET_KEY = "secret"
        assert submit(client_for(customer), django_capture_on_commit_callbacks).status_code == 201


@pytest.mark.django_db
class TestAccount:
    def test_claim_links_order_once(self, network, customer, django_capture_on_commit_callbacks):
        token = submit(client_for(), django_capture_on_commit_callbacks).data["claim_token"]
        response = client_for(customer).post("/api/v1/account/claim/", {"token": token}, format="json")
        assert response.status_code == 200
        order = Order.objects.get()
        assert order.customer == customer and order.claim_token_hash == ""
        again = client_for(make_user("other@example.com")).post("/api/v1/account/claim/", {"token": token}, format="json")
        assert again.status_code == 404

    def test_claim_requires_login(self):
        assert APIClient().post("/api/v1/account/claim/", {"token": "x"}).status_code == 401

    def test_orders_are_private(self, network, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        submit(client_for(customer), django_capture_on_commit_callbacks, items=[{"key": "compost", "quantity": 3}])
        mine = client_for(customer).get("/api/v1/account/orders/").data
        assert len(mine) == 2 and mine[0]["city"] == "Denver"
        other = make_user("other@example.com")
        order = Order.objects.first()
        assert client_for(other).get(f"/api/v1/account/orders/{order.id}/").status_code == 404
        assert client_for(other).get("/api/v1/account/orders/").data == []

    def test_customer_detail_hides_dispatch_and_notes(self, network, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        order.internal_notes = "gate code 1234"
        order.save()
        data = client_for(customer).get(f"/api/v1/account/orders/{order.id}/").data
        assert "internal_notes" not in data and "loads" not in data and "plan_status" not in data
        assert data["items"] == [{"key": "screened_topsoil", "name": "Screened topsoil", "quantity": 10}]
        assert data["quote"]["total"] == "505.00"

    def test_message_thread_and_unread(self, network, customer, staff, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        mail.outbox.clear()

        with django_capture_on_commit_callbacks(execute=True):
            r = client_for(customer).post(
                f"/api/v1/account/orders/{order.id}/messages/", {"body": "Can you come Saturday?"}, format="json"
            )
        assert r.status_code == 201
        assert mail.outbox[-1].to == ["owner@example.com"] and "Can you come Saturday?" in mail.outbox[-1].body

        listing = client_for(staff).get("/api/v1/manage/orders/?unread=1").data
        assert listing["results"][0]["unread_count"] == 1
        client_for(staff).get(f"/api/v1/manage/orders/{order.id}/")
        assert client_for(staff).get("/api/v1/manage/orders/?unread=1").data["count"] == 0

        with django_capture_on_commit_callbacks(execute=True):
            client_for(staff).post(f"/api/v1/manage/orders/{order.id}/messages/", {"body": "Saturday works."}, format="json")
        assert mail.outbox[-1].to == ["pat@example.com"]
        assert client_for(customer).get("/api/v1/account/orders/").data[0]["unread_count"] == 1
        detail = client_for(customer).get(f"/api/v1/account/orders/{order.id}/").data
        assert [m["from_staff"] for m in detail["messages"]] == [False, True]
        assert OrderMessage.objects.filter(read_at__isnull=True).count() == 0

    def test_blank_message_rejected(self, network, customer, django_capture_on_commit_callbacks):
        submit(client_for(customer), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        r = client_for(customer).post(f"/api/v1/account/orders/{order.id}/messages/", {"body": "  "}, format="json")
        assert r.status_code == 400


@pytest.mark.django_db
class TestStaffDashboard:
    def test_permissions(self, customer):
        assert APIClient().get("/api/v1/manage/orders/").status_code == 401
        for path in ("orders/", "summary/", "dispatch/"):
            assert client_for(customer).get(f"/api/v1/manage/{path}").status_code == 403

    def test_list_filters_and_summary(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        submit(client_for(), django_capture_on_commit_callbacks, name="Sam Other", zip_code="80002",
               items=[{"key": "washed_sand", "quantity": 3}])  # fmt: skip
        Order.objects.filter(name="Sam Other").update(status="contacted", plan_status="no_capacity")
        client = client_for(staff)
        assert client.get("/api/v1/manage/orders/?status=new").data["count"] == 1
        assert [r["name"] for r in client.get("/api/v1/manage/orders/?q=sam").data["results"]] == ["Sam Other"]
        assert [r["name"] for r in client.get("/api/v1/manage/orders/?q=80002").data["results"]] == ["Sam Other"]
        assert client.get("/api/v1/manage/orders/?needs_dispatch=1").data["count"] == 1
        summary = client.get("/api/v1/manage/summary/").data
        assert summary["status_counts"]["new"] == 1 and summary["status_counts"]["contacted"] == 1
        assert summary["new_this_week"] == 2 and summary["needs_dispatch"] == 1

    def test_schedule_requires_date_notifies_and_moves_loads(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        mail.outbox.clear()
        client = client_for(staff)
        url = f"/api/v1/manage/orders/{order.id}/"
        assert client.patch(url, {"status": "scheduled"}, format="json").status_code == 400

        new_day = delivery_day(9)
        with django_capture_on_commit_callbacks(execute=True):
            r = client.patch(
                url,
                {"status": "scheduled", "scheduled_date": new_day.isoformat(), "internal_notes": "call first", "notify_customer": True},
                format="json",
            )
        assert r.status_code == 200, r.data
        assert r.data["internal_notes"] == "call first"
        assert [load["date"] for load in r.data["loads"]] == [new_day.isoformat()]
        assert mail.outbox[-1].to == ["pat@example.com"] and "Delivery:" in mail.outbox[-1].body

        # Saving without a change, or without notify, sends nothing.
        with django_capture_on_commit_callbacks(execute=True):
            client.patch(url, {"internal_notes": "x", "notify_customer": True}, format="json")
            client.patch(url, {"status": "delivered", "final_total": "500.00"}, format="json")
        assert len(mail.outbox) == 1
        order.refresh_from_db()
        assert order.delivered_on is not None

    def test_scheduling_on_a_sunday_is_rejected(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        sunday = delivery_day(7)
        while sunday.weekday() != 6:
            sunday += timedelta(days=1)
        r = client_for(staff).patch(f"/api/v1/manage/orders/{order.id}/", {"scheduled_date": sunday.isoformat()}, format="json")
        assert r.status_code == 400

    def test_staff_cannot_rewrite_customer_data(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        client_for(staff).patch(f"/api/v1/manage/orders/{order.id}/", {"estimated_total": "1.00", "name": "X"}, format="json")
        order.refresh_from_db()
        assert order.name == "Pat Customer" and str(order.estimated_total) != "1.00"

    def test_staff_detail_shows_dispatch(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        data = client_for(staff).get(f"/api/v1/manage/orders/{order.id}/").data
        assert data["plan_status"] == "ok"
        assert data["loads"][0]["truck_name"] == "N1" and data["loads"][0]["yard_name"] == "North yard"
        assert [y["code"] for y in data["area"]["yards"]] == ["north", "south"]


@pytest.mark.django_db
class TestDispatchEndpoints:
    def test_reassign_and_replan(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        order = Order.objects.get()
        load = order.loads.get()
        client = client_for(staff)
        url = f"/api/v1/manage/orders/{order.id}/loads/{load.id}/"

        r = client.patch(url, {"truck": network.trucks["S1"].id}, format="json")
        assert r.status_code == 200 and r.data["loads"][0]["truck_name"] == "S1"
        bad = client.patch(url, {"truck": network.trucks["W1"].id}, format="json")
        assert bad.status_code == 400 and "no saved distance" in str(bad.data["truck"])
        r = client.patch(url, {"truck": None}, format="json")
        assert r.data["plan_status"] == "no_capacity"

        r = client.post(f"/api/v1/manage/orders/{order.id}/replan/")
        assert r.status_code == 200 and r.data["plan_status"] == "ok"
        assert r.data["loads"][0]["truck_name"] == "N1"

    def test_replan_needs_products(self, staff, db):
        order = Order.objects.create(name="Sam", request_type=Order.RequestType.CALLBACK)
        assert client_for(staff).post(f"/api/v1/manage/orders/{order.id}/replan/").status_code == 400

    def test_board_and_toggles(self, network, staff, django_capture_on_commit_callbacks):
        submit(client_for(), django_capture_on_commit_callbacks)
        day = delivery_day(7)
        client = client_for(staff)
        board = client.get(f"/api/v1/manage/dispatch/?date={day.isoformat()}").data
        north = next(y for y in board["yards"] if y["code"] == "north")
        assert north["trucks"][0]["loads"][0]["order_name"] == "Pat Customer"
        assert client.get("/api/v1/manage/dispatch/?date=nope").status_code == 400

        stock = YardStock.objects.get(yard__code="north", product="screened_topsoil")
        assert client.patch(f"/api/v1/manage/stock/{stock.id}/", {"in_stock": False, "note": "Friday"}, format="json").status_code == 200
        stock.refresh_from_db()
        assert stock.in_stock is False and stock.note == "Friday"

        truck = network.trucks["N2"]
        assert client.patch(f"/api/v1/manage/trucks/{truck.id}/", {"active": False}, format="json").status_code == 200
        truck.refresh_from_db()
        assert truck.active is False

        days_off = f"/api/v1/manage/trucks/{truck.id}/days-off/"
        assert client.post(days_off, {"date": day.isoformat(), "reason": "Brakes"}, format="json").status_code == 204
        assert TruckDayOff.objects.filter(truck=truck, date=day).exists()
        assert client.delete(f"{days_off}?date={day.isoformat()}").status_code == 204
        assert not TruckDayOff.objects.exists()


@pytest.mark.django_db
class TestCustomerSignup:
    def test_register_customer(self):
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
