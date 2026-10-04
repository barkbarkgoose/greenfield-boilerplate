"""JWT authentication that also ends sessions when the password changes."""

from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .tokens import PASSWORD_CLAIM, password_version


class JWTAuthentication(BaseJWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if validated_token.get(PASSWORD_CLAIM) != password_version(user):
            raise AuthenticationFailed("Session ended. Please sign in again.", code="password_changed")
        return user
