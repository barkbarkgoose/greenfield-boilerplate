"""Tests for the users app: login, registration and password reset."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient

User = get_user_model()

VALID_PASSWORD = "ValidPassword123!"
NEW_PASSWORD = "BrandNewPass456!"


@pytest.fixture(autouse=True)
def _setup(settings):
    cache.clear()  # throttle counters
    settings.SITE_URL = "https://shop.example"
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def sample_user(db):
    return User.objects.create_user(
        email="test@example.com", name="Test User", password=VALID_PASSWORD
    )


def reset_link_parts(body: str) -> tuple[str, str]:
    uid, token = re.search(r"/reset-password/([^/\s]+)/([^/?\s]+)", body).groups()
    return uid, token


@pytest.mark.django_db
class TestAuthViews:
    def test_login_returns_user_payload(self, api_client, sample_user):
        response = api_client.post(
            "/api/v1/auth/login/",
            {"email": sample_user.email, "password": VALID_PASSWORD},
            format="json",
        )
        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data
        # Regression guard: the frontend needs the user payload on login,
        # otherwise it stays logged in with a null user.
        assert response.data["user"] == {
            "id": sample_user.id,
            "email": sample_user.email,
            "name": "Test User",
            "is_staff": False,
        }

    def test_login_email_is_case_insensitive(self, api_client, sample_user):
        response = api_client.post(
            "/api/v1/auth/login/",
            {"email": "Test@Example.com", "password": VALID_PASSWORD},
            format="json",
        )
        assert response.status_code == 200

    def test_register_rejects_existing_email_any_case(self, api_client, sample_user):
        response = api_client.post(
            "/api/v1/auth/register/",
            {"email": "TEST@example.com", "name": "Dup", "password": VALID_PASSWORD},
            format="json",
            HTTP_ACCEPT_LANGUAGE="es",
        )
        assert response.status_code == 400
        assert "Ya existe una cuenta" in str(response.data["email"][0])

    def test_settings_endpoint_is_gone(self, api_client, sample_user):
        api_client.force_authenticate(sample_user)
        assert api_client.get("/api/v1/auth/settings/").status_code == 404


@pytest.mark.django_db
class TestPasswordReset:
    def request_reset(self, client, email, **extra):
        return client.post("/api/v1/auth/password-reset/", {"email": email}, format="json", **extra)

    def test_full_reset_flow(self, api_client, sample_user):
        assert self.request_reset(api_client, "TEST@example.com").status_code == 204
        [email] = mail.outbox
        assert email.to == ["test@example.com"]
        assert "https://shop.example/reset-password/" in email.body
        uid, token = reset_link_parts(email.body)

        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "password": NEW_PASSWORD},
            format="json",
        )
        assert response.status_code == 204
        sample_user.refresh_from_db()
        assert sample_user.check_password(NEW_PASSWORD)

        # The link only works once.
        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "password": "AnotherPass789!"},
            format="json",
        )
        assert response.status_code == 400
        assert "token" in response.data

    def test_unknown_email_gets_same_answer_and_no_mail(self, api_client, db):
        assert self.request_reset(api_client, "nobody@example.com").status_code == 204
        assert mail.outbox == []

    def test_inactive_user_gets_no_mail(self, api_client, sample_user):
        sample_user.is_active = False
        sample_user.save()
        self.request_reset(api_client, sample_user.email)
        assert mail.outbox == []

    def test_spanish_request_gets_spanish_email_and_link(self, api_client, sample_user):
        self.request_reset(api_client, sample_user.email, HTTP_ACCEPT_LANGUAGE="es")
        [email] = mail.outbox
        assert email.subject.startswith("Restablece tu contraseña")
        assert "?lang=es" in email.body

    def test_weak_password_is_rejected(self, api_client, sample_user):
        self.request_reset(api_client, sample_user.email)
        uid, token = reset_link_parts(mail.outbox[0].body)
        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "password": "123"},
            format="json",
        )
        assert response.status_code == 400
        assert "password" in response.data
        sample_user.refresh_from_db()
        assert sample_user.check_password(VALID_PASSWORD)

    @pytest.mark.parametrize("uid, token", [("bogus", "bogus"), ("MQ", "wrong-token")])
    def test_bad_links_are_rejected(self, api_client, sample_user, uid, token):
        response = api_client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "password": NEW_PASSWORD},
            format="json",
        )
        assert response.status_code == 400
        assert "token" in response.data

    def test_reset_requests_are_rate_limited(self, api_client, sample_user):
        codes = [self.request_reset(api_client, sample_user.email).status_code for _ in range(6)]
        assert codes[:5] == [204] * 5
        assert codes[5] == 429

    def test_stale_jwt_is_ignored(self, sample_user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        assert self.request_reset(client, sample_user.email).status_code == 204
