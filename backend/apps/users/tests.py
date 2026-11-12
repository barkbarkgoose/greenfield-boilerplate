"""Tests for the users app: auth payload and UserSettingsView."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.organizations.models import Organization

User = get_user_model()

VALID_PASSWORD = "ValidPassword123!"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def sample_user():
    org = Organization.objects.create(name="Test Org")
    return User.objects.create_user(
        email="test@example.com",
        name="Test User",
        password=VALID_PASSWORD,
        organization=org,
    )


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
        assert response.data["user"]["email"] == sample_user.email


@pytest.mark.django_db
class TestRegistration:
    payload = {"email": "new@example.com", "password": "Sup3r-secret-pw", "name": "New"}

    def test_register_without_organization(self, api_client):
        response = api_client.post("/api/v1/auth/register/", self.payload, format="json")
        assert response.status_code == 201
        assert response.data["organization"] is None

    def test_register_with_organization(self, api_client):
        data = {**self.payload, "organization_name": "Acme"}
        response = api_client.post("/api/v1/auth/register/", data, format="json")
        assert response.status_code == 201
        assert response.data["organization"]["name"] == "Acme"


@pytest.mark.django_db
class TestUserSettingsAPI:
    def test_settings_unauthenticated(self, api_client):
        response = api_client.get("/api/v1/auth/settings/")
        assert response.status_code == 401

    def test_get_settings_authenticated(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        response = api_client.get("/api/v1/auth/settings/")
        assert response.status_code == 200
        assert "theme_colors" in response.data

    def test_update_settings_valid(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        payload = {
            "theme_colors": {
                "primary": "#8b5cf6",
                "accent": "emerald",
            },
            "default_view": "upcoming",
        }
        response = api_client.patch("/api/v1/auth/settings/", payload, format="json")
        assert response.status_code == 200
        assert response.data["theme_colors"]["primary"] == "#8b5cf6"
        assert response.data["theme_colors"]["accent"] == "emerald"
        assert response.data["default_view"] == "upcoming"

        sample_user.refresh_from_db()
        assert sample_user.settings["theme_colors"]["primary"] == "#8b5cf6"

    def test_update_settings_strips_disallowed_keys(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        payload = {
            "theme_colors": {"primary": "#10b981"},
            "is_staff": True,  # Disallowed / dangerous key
            "is_superuser": True,
            "role": "admin",
        }
        response = api_client.patch("/api/v1/auth/settings/", payload, format="json")
        assert response.status_code == 200
        sample_user.refresh_from_db()
        assert not sample_user.is_staff
        assert not sample_user.is_superuser
        assert "is_staff" not in sample_user.settings
        assert "role" not in sample_user.settings

    def test_update_settings_invalid_color_rejected(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        payload = {"theme_colors": {"primary": "javascript:alert(1);"}}
        response = api_client.patch("/api/v1/auth/settings/", payload, format="json")
        assert response.status_code == 400
        assert "theme_colors" in response.data

    def test_api_keys_are_encrypted_at_rest_in_db(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        raw_key = "AIzaSyDummySecretKeyForTesting12345"
        payload = {
            "api_keys": {
                "google": raw_key,
                "anthropic": "sk-ant-testkey67890",
            }
        }
        response = api_client.patch("/api/v1/auth/settings/", payload, format="json")
        assert response.status_code == 200

        # Safe response: raw key is never returned to the frontend.
        assert "api_keys" not in response.data
        status_info = response.data.get("api_keys_status", {})
        assert status_info["google"]["is_configured"] is True
        assert status_info["google"]["preview"].endswith("2345")
        assert raw_key not in status_info["google"]["preview"]

        # Database verification: the raw key is NOT plain text in SQLite.
        sample_user.refresh_from_db()
        stored_keys = sample_user.settings.get("api_keys", {})
        assert stored_keys["google"] != raw_key
        assert stored_keys["google"].startswith("gAAAAA")  # Fernet token

        from apps.users.crypto import decrypt_secret

        assert decrypt_secret(stored_keys["google"]) == raw_key
        assert decrypt_secret(stored_keys["anthropic"]) == "sk-ant-testkey67890"

    def test_api_key_can_be_removed(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        api_client.patch(
            "/api/v1/auth/settings/",
            {"api_keys": {"openai": "sk-test-key-123456"}},
            format="json",
        )

        response = api_client.patch(
            "/api/v1/auth/settings/",
            {"api_keys": {"openai": ""}},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["api_keys_status"]["openai"]["is_configured"] is False


@pytest.mark.django_db
class TestRegistrationFlag:
    payload = {"name": "Closed", "email": "closed@example.com", "password": VALID_PASSWORD}

    def test_config_reports_flag(self, api_client, settings):
        settings.ALLOW_REGISTRATION = False
        response = api_client.get("/api/v1/auth/config/")
        assert response.status_code == 200
        assert response.json()["allow_registration"] is False

    def test_register_blocked_when_disabled(self, api_client, settings):
        settings.ALLOW_REGISTRATION = False
        response = api_client.post("/api/v1/auth/register/", self.payload, format="json")
        assert response.status_code == 404
        assert not User.objects.filter(email="closed@example.com").exists()


@pytest.mark.django_db
class TestAddUserCommand:
    def _run(self, monkeypatch, passwords, *args):
        from django.core.management import call_command

        answers = iter(passwords)
        monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
        call_command("add_user", *args)

    def test_creates_a_user_who_can_log_in(self, monkeypatch, api_client):
        self._run(monkeypatch, [VALID_PASSWORD, VALID_PASSWORD], "me@example.com", "--name", "Me")
        user = User.objects.get(email="me@example.com")
        assert not user.is_staff
        response = api_client.post(
            "/api/v1/auth/login/",
            {"email": "me@example.com", "password": VALID_PASSWORD},
            format="json",
        )
        assert response.status_code == 200

    def test_admin_flag(self, monkeypatch):
        self._run(monkeypatch, [VALID_PASSWORD, VALID_PASSWORD], "boss@example.com", "--name", "Boss", "--admin")
        assert User.objects.get(email="boss@example.com").is_superuser

    def test_rejects_mismatch_weak_and_duplicate(self, monkeypatch, sample_user):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="did not match"):
            self._run(monkeypatch, [VALID_PASSWORD, "other"], "a@example.com", "--name", "A")
        with pytest.raises(CommandError):
            self._run(monkeypatch, ["123", "123"], "a@example.com", "--name", "A")
        with pytest.raises(CommandError, match="already exists"):
            self._run(monkeypatch, [VALID_PASSWORD, VALID_PASSWORD], sample_user.email, "--name", "Dup")
        assert not User.objects.filter(email="a@example.com").exists()


@pytest.mark.django_db
class TestRequireLogin:
    def test_config_reports_flag(self, api_client, settings):
        settings.REQUIRE_LOGIN = False
        assert api_client.get("/api/v1/auth/config/").json()["require_login"] is False
        settings.REQUIRE_LOGIN = True
        assert api_client.get("/api/v1/auth/config/").json()["require_login"] is True

    @pytest.mark.parametrize(
        "require_login, method, signed_in, allowed",
        [
            (True, "get", False, False),
            (True, "get", True, True),
            (False, "get", False, True),
            (False, "head", False, True),
            (False, "post", False, False),
            (False, "delete", False, False),
            (False, "post", True, True),
        ],
    )
    def test_public_read_only(self, settings, sample_user, require_login, method, signed_in, allowed):
        from rest_framework.response import Response
        from rest_framework.test import APIRequestFactory, force_authenticate
        from rest_framework.views import APIView

        from apps.users.permissions import PublicReadOnly

        class Articles(APIView):
            permission_classes = [PublicReadOnly]

            def get(self, request):
                return Response([])

            post = delete = get

        settings.REQUIRE_LOGIN = require_login
        request = getattr(APIRequestFactory(), method)("/articles/")
        if signed_in:
            force_authenticate(request, user=sample_user)
        response = Articles.as_view()(request)
        assert (response.status_code == 200) is allowed

    def test_default_views_stay_private_when_login_is_off(self, api_client, settings):
        settings.REQUIRE_LOGIN = False
        assert api_client.get("/api/v1/auth/settings/").status_code == 401


@pytest.mark.django_db
class TestSessions:
    def _login(self, api_client, user):
        response = api_client.post(
            "/api/v1/auth/login/", {"email": user.email, "password": VALID_PASSWORD}, format="json"
        )
        assert response.status_code == 200
        return response.json()

    def test_logout_revokes_the_refresh_token(self, api_client, sample_user):
        refresh = self._login(api_client, sample_user)["refresh"]
        assert api_client.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code == 200
        assert api_client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json").status_code == 204
        assert api_client.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code == 401

    def test_logout_tolerates_junk(self, api_client):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer expired.junk.token")
        assert api_client.post("/api/v1/auth/logout/", {"refresh": "junk"}, format="json").status_code == 204

    def test_refresh_refused_for_deactivated_user(self, api_client, sample_user):
        refresh = self._login(api_client, sample_user)["refresh"]
        User.objects.filter(pk=sample_user.pk).update(is_active=False)
        assert api_client.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code == 401

    def test_stale_access_token_does_not_block_login(self, api_client, sample_user):
        api_client.credentials(HTTP_AUTHORIZATION="Bearer expired.junk.token")
        self._login(api_client, sample_user)

    def test_password_tokens_are_marked(self, api_client, sample_user):
        from rest_framework_simplejwt.tokens import AccessToken

        data = self._login(api_client, sample_user)
        assert AccessToken(data["access"])["amr"] == "pwd"


@pytest.mark.django_db
class TestPasskeySetupPrompt:
    def _login(self, api_client, user):
        return api_client.post(
            "/api/v1/auth/login/", {"email": user.email, "password": VALID_PASSWORD}, format="json"
        )

    def test_offered_to_users_without_a_passkey(self, api_client, sample_user):
        assert self._login(api_client, sample_user).json()["passkey_setup"] == "offer"

    def test_not_offered_after_dont_ask_again(self, api_client, sample_user):
        api_client.force_authenticate(user=sample_user)
        api_client.patch("/api/v1/auth/settings/", {"skip_passkey_offer": True}, format="json")
        api_client.force_authenticate(user=None)
        assert self._login(api_client, sample_user).json()["passkey_setup"] is None

    def test_required_for_staff_without_a_passkey(self, api_client, sample_user):
        User.objects.filter(pk=sample_user.pk).update(is_staff=True)
        data = self._login(api_client, sample_user).json()
        assert data["passkey_setup"] == "required"
        assert data["user"]["is_staff"] is True
        assert data["user"]["admin_url"].startswith("/")

    def test_staff_with_a_passkey_cannot_use_a_password(self, api_client, sample_user):
        from apps.passkeys.models import Passkey

        User.objects.filter(pk=sample_user.pk).update(is_staff=True)
        Passkey.objects.create(user=sample_user, name="Key", credential_id="abc", public_key=b"x", rp_id="localhost")
        response = self._login(api_client, sample_user)
        assert response.status_code == 403
        assert response.json()["code"] == "passkey_required"
        assert "access" not in response.json()


@pytest.mark.django_db
class TestIsPasskeyAdmin:
    def _check(self, user, amr):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from rest_framework_simplejwt.tokens import AccessToken

        from apps.users.permissions import IsPasskeyAdmin

        token = AccessToken.for_user(user)
        token["amr"] = amr
        request = APIRequestFactory().get("/")
        force_authenticate(request, user=user, token=token)
        from rest_framework.request import Request

        return IsPasskeyAdmin().has_permission(Request(request), None)

    def test_needs_staff_and_a_passkey_sign_in(self, sample_user):
        assert not self._check(sample_user, "passkey")
        sample_user.is_staff = True
        assert not self._check(sample_user, "pwd")
        assert self._check(sample_user, "passkey")


@pytest.mark.django_db
class TestAdminSite:
    def test_not_at_slash_admin(self, client):
        assert client.get("/admin/").status_code == 404

    def test_login_sends_staff_to_the_app(self, client, settings):
        response = client.get(f"/{settings.ADMIN_URL}")
        assert response.status_code == 302
        login = client.get(response["Location"])
        assert login.status_code == 302
        assert login["Location"] == f"/login?redirect=%2F{settings.ADMIN_URL.replace('/', '%2F')}"

    def test_login_ignores_offsite_next(self, client, settings):
        response = client.get(f"/{settings.ADMIN_URL}login/?next=//evil.example/")
        assert "evil" not in response["Location"]

    def test_password_login_form_is_gone(self, client, sample_user, settings):
        response = client.post(
            f"/{settings.ADMIN_URL}login/",
            {"username": sample_user.email, "password": VALID_PASSWORD},
        )
        assert response.status_code == 302
        assert response["Location"].startswith("/login?")
