"""Authentication helpers for endpoints that work with or without a login."""

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken

from apps.users.authentication import JWTAuthentication


class OptionalJWTAuthentication(JWTAuthentication):
    """Like JWTAuthentication, but a bad or expired token means "anonymous".

    Used on the public booking endpoint so a stale token left in the browser
    never turns a customer's booking into a 401.
    """

    def authenticate(self, request):
        try:
            return super().authenticate(request)
        except (InvalidToken, AuthenticationFailed):
            return None
