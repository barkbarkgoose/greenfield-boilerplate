"""Passkey endpoints: add and remove your passkeys, and sign in with one.

Each WebAuthn ceremony is two requests. ``begin`` returns options for the browser plus a
``challenge_id``; ``finish`` posts the browser's response with that id. A challenge is
good for one use within five minutes.
"""

import json
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import login
from django.http.request import validate_host
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from apps.users.tokens import sign_in_payload

from .models import Passkey, PasskeyChallenge

TRANSPORTS = {"ble", "cable", "hybrid", "internal", "nfc", "smart-card", "usb"}
# What a malformed browser response can raise on its way through the library
BAD_RESPONSE = (WebAuthnException, ValueError, TypeError, KeyError)


class PasskeySerializer(serializers.ModelSerializer):
    class Meta:
        model = Passkey
        fields = ["id", "name", "created_at", "last_used_at", "backed_up"]


def relying_party(request) -> tuple[str, str]:
    """(rp_id, origin) of the page the browser is on, from its Origin header.

    The host must be one Django serves (ALLOWED_HOSTS). Each passkey is stored with its
    rp_id and only accepted for that rp_id.
    """
    origin = request.headers.get("Origin", "")
    parts = urlsplit(origin)
    host = parts.hostname or ""
    allowed = settings.ALLOWED_HOSTS
    if settings.DEBUG and not allowed:
        allowed = [".localhost", "127.0.0.1", "[::1]"]  # what Django itself allows then
    if parts.scheme not in ("http", "https") or not host or not validate_host(host, allowed):
        raise PermissionDenied("Passkeys aren't available from this address.")
    return settings.PASSKEY_RP_ID or host, f"{parts.scheme}://{parts.netloc}"


def begin_response(challenge: PasskeyChallenge, options) -> Response:
    return Response({"challenge_id": challenge.id, "options": json.loads(options_to_json(options))})


def expired() -> Response:
    return Response(
        {"detail": "The passkey request expired. Please try again."},
        status=status.HTTP_400_BAD_REQUEST,
    )


class PasskeyListView(APIView):
    """GET the signed-in user's passkeys."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(PasskeySerializer(request.user.passkeys.all(), many=True).data)


class PasskeyDetailView(APIView):
    """DELETE one of your passkeys. Staff can't remove their last one."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        passkey = request.user.passkeys.filter(pk=pk).first()
        if passkey is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.is_staff and request.user.passkeys.count() == 1:
            return Response(
                {"detail": "Admin accounts need a passkey. Add another one before removing this one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        passkey.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RegisterBeginView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        rp_id, origin = relying_party(request)
        user = request.user
        PasskeyChallenge.purge_expired()
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=settings.PASSKEY_RP_NAME,
            user_id=str(user.pk).encode(),
            user_name=user.email,
            user_display_name=user.name or user.email,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            # don't make a second passkey on an authenticator that already has one
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id))
                for p in user.passkeys.filter(rp_id=rp_id)
            ],
        )
        challenge = PasskeyChallenge.objects.create(
            purpose=PasskeyChallenge.REGISTER,
            user=user,
            challenge=options.challenge,
            rp_id=rp_id,
            origin=origin,
        )
        return begin_response(challenge, options)


class RegisterFinishView(APIView):
    """POST {challenge_id, credential, name?}: save the new passkey."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        challenge = PasskeyChallenge.take(
            request.data.get("challenge_id"), PasskeyChallenge.REGISTER, request.user
        )
        if challenge is None:
            return expired()
        credential = request.data.get("credential")
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=bytes(challenge.challenge),
                expected_rp_id=challenge.rp_id,
                expected_origin=challenge.origin,
                require_user_verification=True,
            )
        except BAD_RESPONSE:
            return Response(
                {"detail": "The passkey could not be verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        credential_id = bytes_to_base64url(verified.credential_id)
        if Passkey.objects.filter(credential_id=credential_id).exists():
            return Response(
                {"detail": "This passkey is already registered."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        transports = credential.get("response", {}).get("transports") or []
        passkey = Passkey.objects.create(
            user=request.user,
            name=str(request.data.get("name") or "").strip()[:100] or "Passkey",
            credential_id=credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=[t for t in transports if t in TRANSPORTS] if isinstance(transports, list) else [],
            rp_id=challenge.rp_id,
            backed_up=verified.credential_backed_up,
        )
        return Response(PasskeySerializer(passkey).data, status=status.HTTP_201_CREATED)


class SignInBeginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        rp_id, origin = relying_party(request)
        PasskeyChallenge.purge_expired()
        # No allow-list: the browser offers whichever passkeys it has for this site,
        # so nobody has to type an email first.
        options = generate_authentication_options(
            rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED
        )
        challenge = PasskeyChallenge.objects.create(
            purpose=PasskeyChallenge.SIGN_IN,
            challenge=options.challenge,
            rp_id=rp_id,
            origin=origin,
        )
        return begin_response(challenge, options)


class SignInFinishView(APIView):
    """POST {challenge_id, credential}: the same tokens as a password sign-in.

    Staff also get a Django session, which is the only way into the Django admin.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        failed = Response(
            {"detail": "Passkey sign-in failed."}, status=status.HTTP_401_UNAUTHORIZED
        )
        challenge = PasskeyChallenge.take(
            request.data.get("challenge_id"), PasskeyChallenge.SIGN_IN
        )
        if challenge is None:
            return expired()
        credential = request.data.get("credential")
        credential_id = credential.get("id") if isinstance(credential, dict) else None
        passkey = (
            Passkey.objects.select_related("user")
            .filter(credential_id=str(credential_id), rp_id=challenge.rp_id)
            .first()
        )
        if passkey is None or not passkey.user.is_active:
            return failed
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=bytes(challenge.challenge),
                expected_rp_id=challenge.rp_id,
                expected_origin=challenge.origin,
                credential_public_key=bytes(passkey.public_key),
                credential_current_sign_count=passkey.sign_count,
                require_user_verification=True,
            )
        except BAD_RESPONSE:
            return failed
        passkey.sign_count = verified.new_sign_count
        passkey.backed_up = verified.credential_backed_up
        passkey.last_used_at = timezone.now()
        passkey.save(update_fields=["sign_count", "backed_up", "last_used_at"])

        user = passkey.user
        if user.is_staff:
            login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(sign_in_payload(user, "passkey"))
