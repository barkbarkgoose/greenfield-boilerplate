"""API permissions for public content and admin-only views.

DRF's default stays ``IsAuthenticated``, so a view is private unless it opts in to
``PublicReadOnly``. ``REQUIRE_LOGIN`` is the site-wide switch over those opt-ins.
"""

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission


class PublicReadOnly(BasePermission):
    """Anonymous visitors may read when the site doesn't require a login.

    With ``REQUIRE_LOGIN=True`` (the default) this behaves like ``IsAuthenticated``.
    Writes (POST, PUT, PATCH, DELETE) always need a signed-in user.
    """

    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        return not settings.REQUIRE_LOGIN and request.method in SAFE_METHODS


class IsPasskeyAdmin(BasePermission):
    """Staff who signed in with a passkey. Use it instead of ``IsAdminUser``.

    A staff account that has no passkey yet can still sign in with its password to set
    one up, so ``is_staff`` alone doesn't prove a passkey was used.
    """

    def has_permission(self, request, view):
        user = request.user
        token = request.auth
        return bool(
            user
            and user.is_authenticated
            and user.is_staff
            and token is not None
            and hasattr(token, "get")
            and token.get("amr") == "passkey"
        )
