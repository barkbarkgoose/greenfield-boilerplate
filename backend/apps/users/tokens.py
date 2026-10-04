"""Sign-in tokens with shorter sessions for staff.

Everyone gets a short-lived access token plus a refresh token the frontend uses
to renew it silently. The refresh token's lifetime is the whole session:

* Customers: SIMPLE_JWT lifetimes (60-minute access, 7-day session by default).
* Staff: STAFF_ACCESS_TOKEN_LIFETIME (15 minutes) and STAFF_SESSION_LIFETIME
  (8 hours). After that, staff sign in again, whatever they were doing.

Every token also carries a short fingerprint of the user's password hash
(``pv``). Changing or resetting the password changes it, which signs out every
other device on its next request.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.crypto import salted_hmac
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

PASSWORD_CLAIM = "pv"


def password_version(user) -> str:
    return salted_hmac("users.tokens.password-version", user.password).hexdigest()[:16]


def _staff_access_lifetime(access) -> None:
    access.set_exp(lifetime=settings.STAFF_ACCESS_TOKEN_LIFETIME)


def issue_tokens(user) -> dict:
    """A new session for ``user``: ``{"access", "refresh"}``."""
    refresh = RefreshToken.for_user(user)
    refresh[PASSWORD_CLAIM] = password_version(user)
    if user.is_staff:
        refresh.set_exp(lifetime=settings.STAFF_SESSION_LIFETIME)
    access = refresh.access_token  # copies the pv claim
    if user.is_staff:
        _staff_access_lifetime(access)
    return {"access": str(access), "refresh": str(refresh)}


class SessionEnded(Exception):
    """The refresh token is expired, invalid, or no longer matches the account."""


def refresh_access(raw_refresh: str) -> str:
    """A new access token from a refresh token, re-checking the account."""
    try:
        refresh = RefreshToken(raw_refresh)
    except TokenError as error:
        raise SessionEnded from error
    user = get_user_model().objects.filter(pk=refresh.get("user_id"), is_active=True).first()
    if user is None or refresh.get(PASSWORD_CLAIM) != password_version(user):
        raise SessionEnded
    access = refresh.access_token
    # Uses the account's role now, not when the session started.
    if user.is_staff:
        _staff_access_lifetime(access)
    return str(access)
