"""JWT authentication for the site's API.

On top of simplejwt's checks:

* Sessions end when the password changes (the token's password fingerprint no
  longer matches; see tokens.py).
* A session that must save a passkey first (``psr`` claim) can only reach the
  passkey endpoints; everything else answers 403 ``passkey_setup_required``.
"""

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .tokens import PASSKEY_SETUP_CLAIM, PASSWORD_CLAIM, password_version

PASSKEY_SETUP_PATHS = ("/api/v1/auth/passkeys/",)


class PasskeySetupRequired(PermissionDenied):
    default_detail = "Save a passkey to finish signing in."
    default_code = "passkey_setup_required"


class JWTAuthentication(BaseJWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            _user, token = result
            if token.get(PASSKEY_SETUP_CLAIM) and not request.path.startswith(PASSKEY_SETUP_PATHS):
                raise PasskeySetupRequired()
        return result

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if validated_token.get(PASSWORD_CLAIM) != password_version(user):
            raise AuthenticationFailed("Session ended. Please sign in again.", code="password_changed")
        return user
