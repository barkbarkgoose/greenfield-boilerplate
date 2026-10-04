"""Translation regression tests: every English string has a Spanish pair.

Fails when a key is missing from either text map, is empty, uses different
{placeholders}, isn't BEM-shaped (block__element--modifier), or when a
customer email template has no Spanish version.
"""

import re
import string
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient

from apps.intake import i18n, pricing
from apps.intake.conftest import delivery_day
from apps.intake.models import InvoiceLine, Order

BEM_KEY = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*"  # block
    r"__[a-z0-9]+(?:-[a-z0-9]+)*"  # __element
    r"(?:--[a-z0-9_]+(?:-[a-z0-9_]+)*)?$"  # --modifier (data keys like fill_dirt allowed)
)
EMAIL_DIR = Path(i18n.__file__).parent / "templates" / "intake" / "email"


def placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


class TestTextMaps:
    def test_same_keys_in_both_languages(self):
        en, es = i18n.messages("en"), i18n.messages("es")
        assert sorted(set(en) - set(es)) == [], "missing Spanish text"
        assert sorted(set(es) - set(en)) == [], "Spanish text with no English key"

    @pytest.mark.parametrize("language", i18n.LANGUAGES)
    def test_no_empty_text(self, language):
        empty = [key for key, text in i18n.messages(language).items() if not text.strip()]
        assert empty == []

    def test_placeholders_match(self):
        en, es = i18n.messages("en"), i18n.messages("es")
        mismatched = {key: (placeholders(en[key]), placeholders(es[key])) for key in en if placeholders(en[key]) != placeholders(es[key])}
        assert mismatched == {}

    def test_keys_are_bem(self):
        bad = [key for key in i18n.messages("en") if not BEM_KEY.match(key)]
        assert bad == []

    def test_everything_the_code_looks_up_exists(self):
        keys = set(i18n.messages("en"))
        expected = set()
        for product in pricing.PRODUCTS:
            expected |= {f"product__name--{product.key}", f"product__description--{product.key}"}
        expected |= {f"delivery-window__label--{value}" for value in Order.Window.values}
        expected |= {f"email-status__label--{value}" for value in Order.Status.values}
        expected |= {f"email-status__headline--{value}" for value in Order.Status.values if value != Order.Status.NEW}
        expected |= {f"email-invoice__kind--{value}" for value in InvoiceLine.Kind.values}
        expected |= {f"email-language__label--{language}" for language in i18n.LANGUAGES}
        expected |= {"validation__zip--outside", "validation__zip--contact"}
        assert sorted(expected - keys) == []

    def test_customer_email_templates_have_spanish_versions(self):
        english = [p for p in EMAIL_DIR.glob("*.txt") if p.name.count(".") == 1 and not p.name.startswith("owner_")]
        missing = [p.name for p in english if not (EMAIL_DIR / p.name.replace(".txt", ".es.txt")).exists()]
        assert english and missing == []


@pytest.fixture
def spanish_client():
    client = APIClient()
    client.credentials(HTTP_ACCEPT_LANGUAGE="es-MX,es;q=0.9")
    return client


@pytest.mark.django_db
class TestSpanishRequests:
    def test_catalog_in_spanish(self, spanish_client):
        data = spanish_client.get("/api/v1/intake/catalog/").data
        names = {p["key"]: p["name"] for p in data["products"]}
        assert names["screened_topsoil"] == "Tierra vegetal cribada"
        assert APIClient().get("/api/v1/intake/catalog/").data["products"][0]["name"] == "Screened topsoil"

    def test_validation_errors_in_spanish(self, spanish_client):
        r = spanish_client.post("/api/v1/intake/orders/", {"name": "Ana"}, format="json")
        assert r.status_code == 400
        assert str(r.data["zip_code"][0]) == "Escribe el código postal de entrega."
        # DRF's own messages follow too.
        r = spanish_client.post("/api/v1/intake/orders/", {}, format="json")
        assert "obligatorio" in str(r.data["name"][0]).lower() or "requerido" in str(r.data["name"][0]).lower()

    def test_spanish_order_end_to_end(self, network, spanish_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            r = spanish_client.post(
                "/api/v1/intake/orders/",
                {
                    "name": "Ana",
                    "phone": "555-0100",
                    "contact_consent": True,
                    "email": "ana@example.com",
                    "delivery_address": "1 Calle Mayor",
                    "zip_code": "80202",
                    "items": [{"key": "compost", "quantity": 4}],
                    "preferred_date": delivery_day(10).isoformat(),
                    "delivery_window": "afternoon",
                },
                format="json",
            )
        assert r.status_code == 201, r.data
        assert r.data["quote"]["line_items"][0]["name"] == "Composta"
        order = Order.objects.get()
        assert order.language == "es"

        owner, customer = mail.outbox
        assert owner.subject.startswith("New order") and "Language: Spanish" in owner.body
        assert "Compost: 4 yd" in owner.body and "Composta" not in owner.body
        assert customer.subject.startswith("Recibimos tu pedido")
        assert "Hola Ana" in customer.body and "Composta: 4 yd" in customer.body
        assert "(tarde)" in customer.body and "?lang=es" in customer.body

        # Stored once, rendered per reader: staff see English.
        staff = get_user_model().objects.create_user(email="d@x.com", name="D", password="x", is_staff=True)
        client = APIClient()
        client.force_authenticate(staff)
        detail = client.get(f"/api/v1/manage/orders/{order.id}/").data
        assert detail["quote"]["line_items"][0]["name"] == "Compost"
        assert detail["language"] == "es"

        mail.outbox.clear()
        with django_capture_on_commit_callbacks(execute=True):
            client.patch(
                f"/api/v1/manage/orders/{order.id}/",
                {"status": "scheduled", "scheduled_date": delivery_day(10).isoformat(), "notify_customer": True},
                format="json",
            )
            client.post(f"/api/v1/manage/orders/{order.id}/messages/", {"body": "Nos vemos."}, format="json")
        status_mail, reply_mail = mail.outbox
        assert status_mail.subject == f"Pedido #{order.id}: Programado"
        assert "tu entrega está programada" in status_mail.body and "Entrega:" in status_mail.body
        assert reply_mail.subject.startswith("Respuesta sobre tu pedido")
