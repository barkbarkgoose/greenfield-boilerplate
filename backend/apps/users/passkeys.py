"""Passkeys (WebAuthn) for accounts with ``passkey_required``.

How it works:

* Turn it on per account: ``user.passkey_required = True`` (Django admin or
  shell). ``PASSKEYS_ENABLED=False`` switches the requirement off site-wide.
* Next password sign-in with no passkey saved: the session can only reach the
  passkey endpoints until the person saves one (tokens carry ``psr``, see
  authentication.py). Saving one swaps in a normal session.
* Every sign-in after that: password, then the passkey (Bitwarden, a phone,
  a security key...). No tokens are issued until the passkey checks out.
* Locked out: ``python manage.py reset_passkeys <email>`` deletes their passkeys
  so the next sign-in sets up a new one (``--off`` also drops the requirement).

Passkeys belong to a domain (``PASSKEY_RP_ID``, from ``SITE_URL``) and live in
that environment's database, so local, staging and production each get their
own.

Challenges are stateless: a signed, short-lived token the browser sends back,
used once (tracked in the cache).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils import timezone
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import Passkey, User

CHALLENGE_MAX_AGE = 300  # seconds to finish a passkey prompt
_SALT = "users.passkeys"
_TRANSPORTS = {t.value for t in AuthenticatorTransport}


class PasskeyError(Exception):
    """Why a passkey step failed; the message is safe to show."""


def requirement_applies(user) -> bool:
    return bool(settings.PASSKEYS_ENABLED and user.passkey_required)


def _challenge_token(user, purpose: str, challenge: bytes) -> str:
    return signing.dumps(
        {"u": user.pk, "p": purpose, "c": bytes_to_base64url(challenge)}, salt=_SALT
    )


def _open_challenge(token: str, purpose: str) -> tuple[int, bytes]:
    try:
        data = signing.loads(str(token), salt=_SALT, max_age=CHALLENGE_MAX_AGE)
    except signing.BadSignature as error:  # includes SignatureExpired
        raise PasskeyError("This passkey prompt expired. Try again.") from error
    if data.get("p") != purpose:
        raise PasskeyError("This passkey prompt expired. Try again.")
    # Single use: a captured response can't be replayed.
    if not cache.add(f"passkey-challenge:{data['c']}", 1, CHALLENGE_MAX_AGE):
        raise PasskeyError("This passkey prompt was already used. Try again.")
    return data["u"], base64url_to_bytes(data["c"])


def _descriptors(user) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(passkey.credential_id),
            transports=[AuthenticatorTransport(t) for t in passkey.transports if t in _TRANSPORTS],
        )
        for passkey in user.passkeys.all()
    ]


def _options(options) -> dict:
    return json.loads(options_to_json(options))


# --- Saving a passkey ------------------------------------------------------------


def registration_options(user) -> dict:
    options = generate_registration_options(
        rp_id=settings.PASSKEY_RP_ID,
        rp_name=settings.PASSKEY_RP_NAME,
        user_id=f"user-{user.pk}".encode(),
        user_name=user.email,
        user_display_name=user.name or user.email,
        exclude_credentials=_descriptors(user),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        timeout=CHALLENGE_MAX_AGE * 1000,
    )
    return {
        "options": _options(options),
        "challenge_token": _challenge_token(user, "register", options.challenge),
    }


def register(user, challenge_token: str, credential: dict, name: str = "") -> Passkey:
    user_id, challenge = _open_challenge(challenge_token, "register")
    if user_id != user.pk:
        raise PasskeyError("This passkey prompt expired. Try again.")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.PASSKEY_RP_ID,
            expected_origin=settings.PASSKEY_ORIGINS,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError) as error:
        raise PasskeyError("That passkey couldn't be saved. Try again.") from error
    credential_id = bytes_to_base64url(verified.credential_id)
    if Passkey.objects.filter(credential_id=credential_id).exists():
        raise PasskeyError("That passkey is already saved.")
    transports = (credential.get("response") or {}).get("transports") or []
    return Passkey.objects.create(
        user=user,
        name=(name or "").strip()[:60] or "Passkey",
        credential_id=credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=[t for t in transports if t in _TRANSPORTS],
    )


# --- Signing in with a passkey -----------------------------------------------------


def authentication_options(user) -> dict:
    options = generate_authentication_options(
        rp_id=settings.PASSKEY_RP_ID,
        allow_credentials=_descriptors(user),
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=CHALLENGE_MAX_AGE * 1000,
    )
    return {
        "options": _options(options),
        "challenge_token": _challenge_token(user, "login", options.challenge),
    }


def authenticate(challenge_token: str, credential: dict) -> User:
    """The user a passkey response signs in, or PasskeyError."""
    user_id, challenge = _open_challenge(challenge_token, "login")
    passkey = (
        Passkey.objects.select_related("user")
        .filter(user_id=user_id, user__is_active=True, credential_id=str(credential.get("id", "")))
        .first()
    )
    if passkey is None:
        raise PasskeyError("That passkey isn't saved on this account.")
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.PASSKEY_RP_ID,
            expected_origin=settings.PASSKEY_ORIGINS,
            credential_public_key=bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError) as error:
        raise PasskeyError("That passkey didn't check out. Try again.") from error
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])
    return passkey.user
