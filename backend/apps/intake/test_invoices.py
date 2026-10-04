"""Tests for verified invoices, live updates (polling), the messaging switch and consent."""

from decimal import Decimal

import pytest
from django.core import mail

from apps.intake.models import Invoice, Order, OrderMessage
from apps.intake.test_accounts import client_for, make_user


@pytest.fixture
def customer(db):
    return make_user("pat@example.com")


@pytest.fixture
def staff(db):
    return make_user("dispatch@example.com", staff=True)


@pytest.fixture
def order(db, customer):
    order = Order.objects.create(
        name="Pat Customer",
        email="pat@example.com",
        customer=customer,
        zip_code="80202",
        items={"screened_topsoil": 10},
        is_rush=True,
        language="es",
    )
    order.loads.create(product="screened_topsoil", quantity=10, miles=12)
    return order


def invoice_body(**overrides):
    body = {
        "items": [{"key": "screened_topsoil", "quantity": 12}],
        "loads": [
            {"product": "screened_topsoil", "quantity": 6, "miles": "12"},
            {"product": "screened_topsoil", "quantity": 6, "miles": "4"},
        ],
        "charge_rush_fee": False,
        "lines": [
            {"kind": "service", "description": "Spread in back yard", "quantity": "1.5", "unit_price": "60"},
            {"kind": "fee", "description": "Wait time", "quantity": "1", "unit_price": "25"},
        ],
        "note": "Two drops, front and back.",
        "published": False,
        "notify_customer": False,
    }
    body.update(overrides)
    return body


def url(order, suffix=""):
    return f"/api/v1/manage/orders/{order.id}/invoice/{suffix}"


# 12 yd x $42 = $504; loads $85 + $75 = $160; lines $90 + $25 = $115.
TOTAL = "779.00"


@pytest.mark.django_db
class TestStaffInvoice:
    def test_draft_starts_from_the_order_and_its_loads(self, staff, order):
        data = client_for(staff).get(url(order)).json()
        assert data["exists"] is False
        assert data["items"] == [{"key": "screened_topsoil", "name": "Screened topsoil", "quantity": 10}]
        assert data["loads"] == [{"product": "screened_topsoil", "quantity": 10, "miles": "12.0"}]
        # A rush order keeps the rush fee in its draft.
        assert data["charge_rush_fee"] is True and data["priced"]["rush_fee"] == "50.00"

    def test_preview_reprices_and_sums_lines(self, staff, order):
        response = client_for(staff).post(url(order, "preview/"), invoice_body(), format="json")
        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["totals"]["delivered"] == "664.00"
        assert data["totals"]["services"] == "90.00" and data["totals"]["fees"] == "25.00"
        assert data["totals"]["total"] == TOTAL
        assert data["lines"][0] == {
            "kind": "service", "description": "Spread in back yard", "quantity": "1.5", "unit_price": "60.00", "amount": "90.00",
        }
        assert not Invoice.objects.exists()

    def test_invoices_ignore_order_minimums(self, staff, order):
        body = invoice_body(items=[{"key": "fill_dirt", "quantity": 2}], loads=[], lines=[])
        data = client_for(staff).post(url(order, "preview/"), body, format="json").json()
        assert data["items"][0]["quantity"] == 2 and data["totals"]["total"] == "36.00"

    def test_save_draft_is_hidden_from_customer(self, staff, customer, order):
        assert client_for(staff).put(url(order), invoice_body(), format="json").status_code == 200
        order.refresh_from_db()
        assert order.invoice.total == Decimal(TOTAL) and order.final_total is None
        assert client_for(customer).get(f"/api/v1/account/orders/{order.id}/").json()["invoice"] is None
        assert client_for(staff).get(f"/api/v1/manage/orders/{order.id}/").json()["invoice"]["totals"]["total"] == TOTAL

    def test_publish_shows_invoice_sets_final_total_and_emails(
        self, staff, customer, order, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = client_for(staff).put(url(order), invoice_body(published=True, notify_customer=True), format="json")
        assert response.json()["published_at"]
        order.refresh_from_db()
        assert order.final_total == Decimal(TOTAL)

        detail = client_for(customer).get(f"/api/v1/account/orders/{order.id}/", HTTP_ACCEPT_LANGUAGE="es").json()
        invoice = detail["invoice"]
        assert invoice["totals"]["total"] == TOTAL
        # Product names follow the reader's language; staff-typed lines don't change.
        assert invoice["priced"]["line_items"][0]["name"] == "Tierra vegetal cribada"
        assert invoice["lines"][0]["description"] == "Spread in back yard"

        [email] = mail.outbox
        assert email.to == ["pat@example.com"]
        assert email.subject == f"Tu factura del pedido #{order.id}"
        assert "Servicio: Spread in back yard x1.5: $90.00" in email.body
        assert "Entrega, 6 yd de tierra vegetal cribada (4.0 mi): $75.00" in email.body
        assert f"Total: ${TOTAL}" in email.body

    def test_editing_a_published_invoice_does_not_email_again(self, staff, order, django_capture_on_commit_callbacks):
        client = client_for(staff)
        with django_capture_on_commit_callbacks(execute=True):
            client.put(url(order), invoice_body(published=True, notify_customer=True), format="json")
            first_published = Order.objects.get(pk=order.pk).invoice.published_at
            client.put(url(order), invoice_body(published=True, notify_customer=True, lines=[]), format="json")
        assert len(mail.outbox) == 1
        order.refresh_from_db()
        assert order.invoice.published_at == first_published
        assert order.final_total == Decimal("664.00")

    def test_published_invoice_overrides_manual_final_total(self, staff, order):
        client = client_for(staff)
        client.put(url(order), invoice_body(published=True), format="json")
        client.patch(f"/api/v1/manage/orders/{order.id}/", {"final_total": "1.00"}, format="json")
        order.refresh_from_db()
        assert order.final_total == Decimal(TOTAL)

    def test_unpublish_and_delete_clear_final_total(self, staff, customer, order):
        client = client_for(staff)
        client.put(url(order), invoice_body(published=True), format="json")
        client.put(url(order), invoice_body(published=False), format="json")
        order.refresh_from_db()
        assert order.final_total is None
        client.put(url(order), invoice_body(published=True), format="json")
        assert client.delete(url(order)).status_code == 204
        order.refresh_from_db()
        assert order.final_total is None and not Invoice.objects.exists()

    def test_rush_fee_is_staff_choice(self, staff, order):
        data = client_for(staff).post(url(order, "preview/"), invoice_body(charge_rush_fee=True, lines=[]), format="json").json()
        assert data["priced"]["rush_fee"] == "50.00" and data["totals"]["total"] == "714.00"

    @pytest.mark.parametrize(
        "line, field",
        [
            ({"kind": "fee", "description": "Wait", "quantity": "1", "unit_price": "-5"}, "unit_price"),
            ({"kind": "fee", "description": "Wait", "quantity": "0", "unit_price": "5"}, "quantity"),
            ({"kind": "fee", "description": "", "quantity": "1", "unit_price": "5"}, "description"),
            ({"kind": "bribe", "description": "x", "quantity": "1", "unit_price": "5"}, "kind"),
        ],
    )
    def test_line_validation(self, staff, order, line, field):
        response = client_for(staff).put(url(order), invoice_body(lines=[line]), format="json")
        assert response.status_code == 400
        assert field in response.json()["lines"]["0"]

    def test_bad_items_and_loads(self, staff, order):
        client = client_for(staff)
        r = client.put(url(order), invoice_body(items=[{"key": "gold", "quantity": 1}]), format="json")
        assert r.status_code == 400 and "items" in r.json()
        r = client.put(url(order), invoice_body(loads=[{"product": "compost", "quantity": 0, "miles": "3"}]), format="json")
        assert r.status_code == 400 and "loads" in r.json()

    def test_discount_adjustment_can_be_negative(self, staff, order):
        line = {"kind": "adjustment", "description": "Repeat customer", "quantity": "1", "unit_price": "-10"}
        data = client_for(staff).post(url(order, "preview/"), invoice_body(lines=[line]), format="json").json()
        assert data["totals"]["adjustments"] == "-10.00" and data["totals"]["total"] == "654.00"

    def test_customers_cannot_use_staff_invoice_endpoints(self, customer, order):
        client = client_for(customer)
        assert client.get(url(order)).status_code == 403
        assert client.put(url(order), invoice_body(), format="json").status_code == 403
        assert client.post(url(order, "preview/"), invoice_body(), format="json").status_code == 403


@pytest.mark.django_db
class TestLiveUpdates:
    def test_customer_gets_new_messages_after_id_and_marks_them_read(self, customer, order):
        old = OrderMessage.objects.create(order=order, body="Earlier", from_staff=True)
        new = OrderMessage.objects.create(order=order, body="Truck is on the way", from_staff=True)
        data = client_for(customer).get(f"/api/v1/account/orders/{order.id}/updates/", {"after": old.id}).json()
        assert [m["body"] for m in data["messages"]] == ["Truck is on the way"] and data["updated_at"]
        new.refresh_from_db()
        assert new.read_at is not None

    def test_updated_at_moves_when_staff_change_the_order(self, staff, customer, order):
        poll = f"/api/v1/account/orders/{order.id}/updates/"
        before = client_for(customer).get(poll).json()["updated_at"]
        client_for(staff).put(url(order), invoice_body(published=True), format="json")
        assert client_for(customer).get(poll).json()["updated_at"] != before

    def test_customer_cannot_poll_someone_elses_order(self, order):
        other = make_user("other@example.com")
        assert client_for(other).get(f"/api/v1/account/orders/{order.id}/updates/").status_code == 404

    def test_staff_poll_marks_customer_messages_read(self, staff, order):
        message = OrderMessage.objects.create(order=order, body="Question", from_staff=False)
        data = client_for(staff).get(f"/api/v1/manage/orders/{order.id}/updates/").json()
        assert [m["body"] for m in data["messages"]] == ["Question"]
        message.refresh_from_db()
        assert message.read_at is not None


@pytest.mark.django_db
class TestMessagingSwitch:
    """INTAKE_MESSAGING_ENABLED=False (the launch default) hides message threads."""

    @pytest.fixture(autouse=True)
    def _off(self, settings):
        settings.INTAKE_MESSAGING_ENABLED = False

    def test_message_and_update_endpoints_are_off(self, customer, staff, order):
        c, s = client_for(customer), client_for(staff)
        assert c.post(f"/api/v1/account/orders/{order.id}/messages/", {"body": "Hi"}).status_code == 404
        assert c.get(f"/api/v1/account/orders/{order.id}/updates/").status_code == 404
        assert s.post(f"/api/v1/manage/orders/{order.id}/messages/", {"body": "Hi"}).status_code == 404
        assert s.get(f"/api/v1/manage/orders/{order.id}/updates/").status_code == 404
        assert not OrderMessage.objects.exists()

    def test_order_pages_say_messaging_is_off(self, customer, staff, order):
        assert client_for(customer).get(f"/api/v1/account/orders/{order.id}/").json()["messaging_enabled"] is False
        assert client_for(staff).get(f"/api/v1/manage/orders/{order.id}/").json()["messaging_enabled"] is False


@pytest.mark.django_db
class TestConsentForStaff:
    def test_staff_see_consent_and_owner_email_mentions_it(self, staff, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = client_for().post(
                "/api/v1/intake/orders/",
                {
                    "request_type": "callback",
                    "name": "Sam",
                    "phone": "555-0100",
                    "notes": "Call me about 40 yards of fill",
                    "contact_consent": True,
                    "marketing_consent": True,
                },
                format="json",
            )
        assert response.status_code == 201
        detail = client_for(staff).get(f"/api/v1/manage/orders/{response.data['id']}/").json()
        assert detail["contact_consent"] is True and detail["marketing_consent"] is True and detail["consent_at"]
        [owner_email] = mail.outbox
        assert "Promotions by text/email: yes" in owner_email.body

    def test_staff_cannot_change_consent(self, staff, order):
        client_for(staff).patch(f"/api/v1/manage/orders/{order.id}/", {"marketing_consent": True}, format="json")
        order.refresh_from_db()
        assert order.marketing_consent is False
