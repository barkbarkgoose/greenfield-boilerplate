"""Passkey tests, using a small software authenticator (a P-256 key) that
produces real WebAuthn responses the server verifies end to end."""

import hashlib
import json
import os
import struct
from io import StringIO

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient
from webauthn.helpers import bytes_to_base64url

from apps.users.models import Passkey

User = get_user_model()
PASSWORD = "ValidPassword123!"
ORIGIN = "https://shop.example"
RP_ID = "shop.example"


class SoftAuthenticator:
    """Just enough of a passkey provider (think Bitwarden) for tests."""

    def __init__(self, origin=ORIGIN, rp_id=RP_ID):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.origin = origin
        self.rp_id = rp_id
        self.counter = 0

    def _client_data(self, kind, challenge):
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}
        ).encode()

    def _rp_hash(self):
        return hashlib.sha256(self.rp_id.encode()).digest()

    def create(self, options):
        numbers = self.key.public_key().public_numbers()
        cose_key = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
        )
        auth_data = (
            self._rp_hash()
            + bytes([0x45])  # user present + verified + attested credential data
            + struct.pack(">I", self.counter)
            + bytes(16)  # AAGUID
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + cose_key
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = bytes_to_base64url(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(self._client_data("webauthn.create", options["challenge"])),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal", "hybrid"],
            },
        }

    def get(self, options):
        self.counter += 1
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = self._rp_hash() + bytes([0x05]) + struct.pack(">I", self.counter)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        cid = bytes_to_base64url(self.credential_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
            },
        }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        email="mech@example.com", name="Mech", password=PASSWORD, is_staff=True, passkey_required=True
    )


def login(client, email="mech@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")


def authed(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def register_passkey(client, authenticator, name="Bitwarden"):
    options = client.post("/api/v1/auth/passkeys/register/options/").json()
    return client.post(
        "/api/v1/auth/passkeys/register/",
        {
            "challenge_token": options["challenge_token"],
            "credential": authenticator.create(options["options"]),
            "name": name,
        },
        format="json",
    )


def sign_in_with_passkey(authenticator, email="mech@example.com"):
    client = APIClient()
    step1 = login(client, email).json()
    assert step1["passkey_required"] is True
    assert "access" not in step1
    return client.post(
        "/api/v1/auth/passkeys/login/",
        {"challenge_token": step1["challenge_token"], "credential": authenticator.get(step1["options"])},
        format="json",
    )


@pytest.mark.django_db
class TestPasskeyFlow:
    def test_first_sign_in_must_save_a_passkey_then_it_is_required(self, staff):
        first = login(APIClient()).json()
        assert first["passkey_setup_required"] is True
        limited = authed(first["access"])

        # Until a passkey is saved, only the passkey endpoints work.
        blocked = limited.get("/api/v1/manage/summary/")
        assert blocked.status_code == 403
        assert blocked.json()["detail"].startswith("Save a passkey")
        assert limited.get("/api/v1/auth/passkeys/").json() == {"required": True, "passkeys": []}

        bitwarden = SoftAuthenticator()
        saved = register_passkey(limited, bitwarden)
        assert saved.status_code == 201, saved.json()
        assert saved.json()["passkey"]["name"] == "Bitwarden"
        # The swapped-in session works everywhere.
        assert authed(saved.json()["access"]).get("/api/v1/manage/summary/").status_code == 200

        # From now on a password alone gets no tokens; the passkey finishes it.
        response = sign_in_with_passkey(bitwarden)
        assert response.status_code == 200, response.json()
        assert authed(response.json()["access"]).get("/api/v1/manage/summary/").status_code == 200
        assert Passkey.objects.get().last_used_at is not None

    def test_wrong_passkey_or_replay_is_rejected(self, staff):
        bitwarden = SoftAuthenticator()
        register_passkey(authed(login(APIClient()).json()["access"]), bitwarden)

        step1 = login(APIClient()).json()
        stranger = SoftAuthenticator()  # not saved on this account
        response = APIClient().post(
            "/api/v1/auth/passkeys/login/",
            {"challenge_token": step1["challenge_token"], "credential": stranger.get(step1["options"])},
            format="json",
        )
        assert response.status_code == 400

        step1 = login(APIClient()).json()
        body = {"challenge_token": step1["challenge_token"], "credential": bitwarden.get(step1["options"])}
        assert APIClient().post("/api/v1/auth/passkeys/login/", body, format="json").status_code == 200
        # The same response can't be used twice.
        assert APIClient().post("/api/v1/auth/passkeys/login/", body, format="json").status_code == 400

    def test_passkey_from_another_site_is_rejected(self, staff):
        phishing = SoftAuthenticator(origin="https://shop-example.evil", rp_id="shop-example.evil")
        response = register_passkey(authed(login(APIClient()).json()["access"]), phishing)
        assert response.status_code == 400
        assert not Passkey.objects.exists()

    def test_last_passkey_cannot_be_removed_while_required(self, staff):
        client = authed(login(APIClient()).json()["access"])
        first = register_passkey(client, SoftAuthenticator()).json()
        client = authed(first["access"])
        assert client.delete(f"/api/v1/auth/passkeys/{first['passkey']['id']}/").status_code == 400

        second = register_passkey(client, SoftAuthenticator(), name="Phone").json()
        assert client.delete(f"/api/v1/auth/passkeys/{first['passkey']['id']}/").status_code == 204
        assert [p["name"] for p in client.get("/api/v1/auth/passkeys/").json()["passkeys"]] == ["Phone"]
        assert second["passkey"]["name"] == "Phone"

    def test_accounts_without_the_requirement_sign_in_as_usual(self, db):
        User.objects.create_user(email="pat@example.com", name="Pat", password=PASSWORD)
        data = login(APIClient(), "pat@example.com").json()
        assert data["access"] and "passkey_required" not in data
        assert data["user"]["passkey_required"] is False

    def test_site_wide_switch_turns_the_requirement_off(self, staff, settings):
        settings.PASSKEYS_ENABLED = False
        data = login(APIClient()).json()
        assert data["access"] and "passkey_setup_required" not in data
        assert authed(data["access"]).get("/api/v1/manage/summary/").status_code == 200

    def test_setup_session_cannot_reach_the_garage(self, staff):
        limited = authed(login(APIClient()).json()["access"])
        assert limited.get("/api/v1/garage/requests/").status_code == 403


@pytest.mark.django_db
class TestResetPasskeys:
    def test_reset_deletes_passkeys_and_next_sign_in_sets_up_again(self, staff):
        register_passkey(authed(login(APIClient()).json()["access"]), SoftAuthenticator())
        out = StringIO()
        call_command("reset_passkeys", "MECH@example.com", stdout=out)
        assert "deleted 1 passkey" in out.getvalue()
        assert login(APIClient()).json()["passkey_setup_required"] is True

    def test_off_and_on(self, staff):
        call_command("reset_passkeys", staff.email, "--off", stdout=StringIO())
        staff.refresh_from_db()
        assert staff.passkey_required is False
        call_command("reset_passkeys", staff.email, "--on", stdout=StringIO())
        staff.refresh_from_db()
        assert staff.passkey_required is True
