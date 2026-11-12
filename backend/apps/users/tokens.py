"""The response every successful sign-in returns, whether by password or passkey."""

from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import UserSerializer


def passkey_setup(user) -> str | None:
    """What the app should ask after sign-in: "required" for staff without a passkey,
    "offer" for other users without one (unless they said not to ask), else None."""
    if user.passkeys.exists():
        return None
    if user.is_staff:
        return "required"
    if (user.settings or {}).get("skip_passkey_offer"):
        return None
    return "offer"


def sign_in_payload(user, method: str) -> dict:
    """JWTs plus the user. ``method`` ("pwd" or "passkey") is stored in the tokens as
    the ``amr`` claim, which ``IsPasskeyAdmin`` checks."""
    refresh = RefreshToken.for_user(user)
    refresh["amr"] = method
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": UserSerializer(user).data,
        "passkey_setup": passkey_setup(user),
    }
