"""Tests for passkeys: a software authenticator drives the real WebAuthn verification."""

import base64
import hashlib
import json
import os
from datetime import timedelta

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.passkeys.models import Passkey, PasskeyChallenge

User = get_user_model()

ORIGIN = "http://localhost:5177"
PASSWORD = "ValidPassword123!"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class SoftAuthenticator:
    """A passkey held in memory that answers like a browser would (attestation "none")."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.sign_count = 0
        self.user_handle = None

    def _auth_data(self, rp_id: str, flags: int, attested: bytes = b"") -> bytes:
        rp_hash = hashlib.sha256(rp_id.encode()).digest()
        return rp_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big") + attested

    @staticmethod
    def _client_data(kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin}).encode()

    def create(self, options: dict, origin: str = ORIGIN) -> dict:
        numbers = self.key.public_key().public_numbers()
        cose_key = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
        )
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + cose_key
        auth_data = self._auth_data(options["rp"]["id"], 0x01 | 0x04 | 0x40, attested)  # UP, UV, AT
        self.user_handle = options["user"]["id"]
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"], origin)),
                "attestationObject": b64(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})),
                "transports": ["internal", "bogus"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict, origin: str = ORIGIN) -> dict:
        self.sign_count += 1
        auth_data = self._auth_data(options["rpId"], 0x01 | 0x04)
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": self.user_handle,
            },
            "clientExtensionResults": {},
        }


@pytest.fixture
def client():
    return APIClient(HTTP_ORIGIN=ORIGIN)


@pytest.fixture
def user():
    return User.objects.create_user(email="user@example.com", name="User", password=PASSWORD)


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", name="Staff", password=PASSWORD, is_staff=True
    )


def add_passkey(client, user, authenticator=None, name="Laptop"):
    authenticator = authenticator or SoftAuthenticator()
    client.force_authenticate(user=user)
    begin = client.post("/api/v1/auth/passkeys/register/begin/").json()
    response = client.post(
        "/api/v1/auth/passkeys/register/finish/",
        {
            "challenge_id": begin["challenge_id"],
            "credential": authenticator.create(begin["options"]),
            "name": name,
        },
        format="json",
    )
    client.force_authenticate(user=None)
    return authenticator, response


def sign_in(client, authenticator):
    begin = client.post("/api/v1/auth/passkeys/login/begin/").json()
    return client.post(
        "/api/v1/auth/passkeys/login/finish/",
        {"challenge_id": begin["challenge_id"], "credential": authenticator.get(begin["options"])},
        format="json",
    )


def token_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@pytest.mark.django_db
class TestRegister:
    def test_register_saves_the_passkey(self, client, user):
        _, response = add_passkey(client, user)
        assert response.status_code == 201
        assert response.json()["name"] == "Laptop"
        passkey = Passkey.objects.get(user=user)
        assert passkey.rp_id == "localhost"
        assert passkey.transports == ["internal"]

    def test_begin_needs_a_login(self, client):
        assert client.post("/api/v1/auth/passkeys/register/begin/").status_code == 401

    def test_options_exclude_existing_passkeys(self, client, user):
        add_passkey(client, user)
        client.force_authenticate(user=user)
        options = client.post("/api/v1/auth/passkeys/register/begin/").json()["options"]
        assert len(options["excludeCredentials"]) == 1
        assert options["authenticatorSelection"]["residentKey"] == "required"

    def test_challenge_is_bound_to_the_user(self, client, user, staff):
        client.force_authenticate(user=user)
        begin = client.post("/api/v1/auth/passkeys/register/begin/").json()
        client.force_authenticate(user=staff)
        response = client.post(
            "/api/v1/auth/passkeys/register/finish/",
            {"challenge_id": begin["challenge_id"], "credential": SoftAuthenticator().create(begin["options"])},
            format="json",
        )
        assert response.status_code == 400
        assert not Passkey.objects.exists()

    def test_wrong_origin_is_rejected(self, client, user):
        client.force_authenticate(user=user)
        begin = client.post("/api/v1/auth/passkeys/register/begin/").json()
        credential = SoftAuthenticator().create(begin["options"], origin="http://localhost:9999")
        response = client.post(
            "/api/v1/auth/passkeys/register/finish/",
            {"challenge_id": begin["challenge_id"], "credential": credential},
            format="json",
        )
        assert response.status_code == 400

    def test_host_must_be_allowed(self, user):
        client = APIClient(HTTP_ORIGIN="https://evil.example")
        client.force_authenticate(user=user)
        assert client.post("/api/v1/auth/passkeys/register/begin/").status_code == 403


@pytest.mark.django_db
class TestSignIn:
    def test_sign_in_returns_passkey_tokens(self, client, user):
        authenticator, _ = add_passkey(client, user)
        response = sign_in(client, authenticator)
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == user.email
        assert data["user"]["has_passkey"] is True
        assert data["passkey_setup"] is None
        assert token_claims(data["access"])["amr"] == "passkey"
        passkey = Passkey.objects.get(user=user)
        assert passkey.sign_count == 1
        assert passkey.last_used_at is not None

    def test_challenge_is_single_use(self, client, user):
        authenticator, _ = add_passkey(client, user)
        begin = client.post("/api/v1/auth/passkeys/login/begin/").json()
        body = {"challenge_id": begin["challenge_id"], "credential": authenticator.get(begin["options"])}
        assert client.post("/api/v1/auth/passkeys/login/finish/", body, format="json").status_code == 200
        assert client.post("/api/v1/auth/passkeys/login/finish/", body, format="json").status_code == 400

    def test_expired_challenge(self, client, user):
        authenticator, _ = add_passkey(client, user)
        begin = client.post("/api/v1/auth/passkeys/login/begin/").json()
        PasskeyChallenge.objects.update(created_at=PasskeyChallenge.objects.get().created_at - timedelta(minutes=6))
        response = client.post(
            "/api/v1/auth/passkeys/login/finish/",
            {"challenge_id": begin["challenge_id"], "credential": authenticator.get(begin["options"])},
            format="json",
        )
        assert response.status_code == 400

    def test_unknown_passkey(self, client, user):
        response = sign_in(client, SoftAuthenticator())
        assert response.status_code == 401

    def test_signature_from_another_key_fails(self, client, user):
        authenticator, _ = add_passkey(client, user)
        authenticator.key = ec.generate_private_key(ec.SECP256R1())
        assert sign_in(client, authenticator).status_code == 401

    def test_inactive_user(self, client, user):
        authenticator, _ = add_passkey(client, user)
        User.objects.filter(pk=user.pk).update(is_active=False)
        assert sign_in(client, authenticator).status_code == 401

    def test_garbage_is_rejected(self, client):
        begin = client.post("/api/v1/auth/passkeys/login/begin/").json()
        response = client.post(
            "/api/v1/auth/passkeys/login/finish/",
            {"challenge_id": begin["challenge_id"], "credential": "nope"},
            format="json",
        )
        assert response.status_code == 401

    def test_only_staff_get_an_admin_session(self, client, user, staff):
        user_key, _ = add_passkey(client, user)
        sign_in(client, user_key)
        assert client.get(f"/{settings.ADMIN_URL}").status_code == 302

        staff_key, _ = add_passkey(client, staff)
        sign_in(client, staff_key)
        assert client.get(f"/{settings.ADMIN_URL}").status_code == 200


@pytest.mark.django_db
class TestManage:
    def test_list_and_delete(self, client, user):
        add_passkey(client, user)
        client.force_authenticate(user=user)
        passkeys = client.get("/api/v1/auth/passkeys/").json()
        assert [p["name"] for p in passkeys] == ["Laptop"]
        assert client.delete(f"/api/v1/auth/passkeys/{passkeys[0]['id']}/").status_code == 204
        assert not Passkey.objects.exists()

    def test_cannot_delete_someone_elses(self, client, user, staff):
        add_passkey(client, staff)
        client.force_authenticate(user=user)
        passkey = Passkey.objects.get(user=staff)
        assert client.delete(f"/api/v1/auth/passkeys/{passkey.pk}/").status_code == 404

    def test_staff_keep_their_last_passkey(self, client, staff):
        add_passkey(client, staff)
        client.force_authenticate(user=staff)
        first = Passkey.objects.get()
        assert client.delete(f"/api/v1/auth/passkeys/{first.pk}/").status_code == 400
        add_passkey(client, staff, name="Phone")
        client.force_authenticate(user=staff)
        assert client.delete(f"/api/v1/auth/passkeys/{first.pk}/").status_code == 204

    def test_reset_passkeys_command(self, client, staff):
        authenticator, _ = add_passkey(client, staff)
        refresh = sign_in(client, authenticator).json()["refresh"]
        call_command("reset_passkeys", staff.email)
        assert not Passkey.objects.exists()
        assert client.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code == 401
        # back to a password sign-in that asks for a new passkey
        response = client.post(
            "/api/v1/auth/login/", {"email": staff.email, "password": PASSWORD}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["passkey_setup"] == "required"
