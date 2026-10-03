"""Translation regression tests: every English string has a Spanish pair.

Fails when a key is missing from either text map, is empty, uses different
{placeholders}, isn't BEM-shaped (block__element--modifier), or when a
customer email template has no Spanish version.
"""

import re
import string
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.intake import i18n, pricing
from apps.intake.models import ServiceRequest, VehicleType
from apps.organizations.models import Organization

BEM_KEY = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*"  # block
    r"__[a-z0-9]+(?:-[a-z0-9]+)*"  # __element
    r"(?:--[a-z0-9_]+(?:-[a-z0-9_]+)*)?$"  # --modifier (data keys like brake_pads allowed)
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
        for service in pricing.SERVICES:
            expected |= {f"service__name--{service.key}", f"service__description--{service.key}"}
            expected.add(f"service__unit--{service.unit or 'job'}")
        for bundle in pricing.BUNDLES:
            expected |= {f"bundle__name--{bundle.key}", f"bundle__description--{bundle.key}"}
        expected |= {f"vehicle-type__label--{value}" for value in VehicleType.values}
        expected |= {f"email-status__label--{value}" for value in ServiceRequest.Status.values}
        expected |= {
            f"email-status__headline--{value}"
            for value in ServiceRequest.Status.values
            if value != ServiceRequest.Status.NEW
        }
        expected |= {f"email-language__label--{language}" for language in i18n.LANGUAGES}
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
    @pytest.fixture(autouse=True)
    def _setup(self, settings):
        cache.clear()
        settings.INTAKE_NOTIFY_EMAILS = ["owner@example.com"]
        settings.SITE_URL = "https://shop.example"
        settings.TURNSTILE_SECRET_KEY = ""
        yield
        cache.clear()

    def test_catalog_in_spanish(self, spanish_client):
        data = spanish_client.get("/api/v1/intake/catalog/").data
        names = {s["key"]: s["name"] for s in data["services"]}
        assert names["brake_pads"] == "Pastillas de freno"
        assert data["deals"][1]["name"].startswith("Tarifa")
        assert APIClient().get("/api/v1/intake/catalog/").data["services"][0]["name"] == "Brake pads"

    def test_validation_errors_in_spanish(self, spanish_client):
        r = spanish_client.post("/api/v1/intake/requests/", {"name": "Ana"}, format="json")
        assert r.status_code == 400
        assert str(r.data["vin"][0]) == "Necesito el VIN para pedir las piezas correctas."
        # DRF's own messages follow too.
        r = spanish_client.post("/api/v1/intake/requests/", {}, format="json")
        assert "obligatorio" in str(r.data["name"][0]).lower() or "requerido" in str(r.data["name"][0]).lower()

    def test_spanish_booking_end_to_end(self, spanish_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            r = spanish_client.post(
                "/api/v1/intake/requests/",
                {
                    "name": "Ana",
                    "email": "ana@example.com",
                    "vin": "1HGCM82633A004352",
                    "services": [{"key": "brake_pads", "quantity": 2}, {"key": "brake_rotors", "quantity": 2}, {"key": "oil_change"}],
                    "preferred_date": (timezone.localdate() + timedelta(days=20)).isoformat(),
                },
                format="json",
            )
        assert r.status_code == 201
        assert r.data["estimate"]["line_items"][0]["name"] == "Pastillas de freno"
        req = ServiceRequest.objects.get()
        assert req.language == "es"

        owner, customer = mail.outbox
        assert owner.subject.startswith("New booking") and "Language: Spanish" in owner.body
        assert "Brake pads" in owner.body and "Pastillas" not in owner.body
        assert customer.subject.startswith("Recibimos tu solicitud")
        assert "Hola Ana" in customer.body and "Pastillas de freno" in customer.body
        assert "?lang=es" in customer.body and "sin margen" in customer.body
        assert "Cambio de aceite y filtro gratis con un trabajo de 2+ h" in customer.body

        # Stored once, rendered per reader: the mechanic sees English.
        org = Organization.objects.create(name="o")
        staff = get_user_model().objects.create_user(
            email="m@x.com", name="M", password="x", organization=org, is_staff=True
        )
        client = APIClient()
        client.force_authenticate(staff)
        detail = client.get(f"/api/v1/manage/requests/{req.id}/").data
        assert detail["estimate"]["line_items"][0]["name"] == "Brake pads"
        assert detail["language"] == "es"

        mail.outbox.clear()
        when = (timezone.now() + timedelta(days=14)).replace(microsecond=0)
        with django_capture_on_commit_callbacks(execute=True):
            client.patch(
                f"/api/v1/manage/requests/{req.id}/",
                {"status": "scheduled", "scheduled_for": when.isoformat(), "notify_customer": True},
                format="json",
            )
            client.post(f"/api/v1/manage/requests/{req.id}/messages/", {"body": "Nos vemos."}, format="json")
        status_mail, reply_mail = mail.outbox
        assert status_mail.subject == f"Solicitud #{req.id}: Programada"
        assert "tu cita está programada" in status_mail.body and "Cita:" in status_mail.body
        assert reply_mail.subject.startswith("Respuesta sobre tu solicitud")
