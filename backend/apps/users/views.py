"""Users app views."""

from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    UserSettingsSerializer,
    format_safe_user_settings,
)
from .tokens import sign_in_payload

User = get_user_model()


class UserSettingsView(APIView):
    """
    Retrieve and update the authenticated user's UI settings.

    --------------------------------------------------------------------------
    SECURITY CONSIDERATIONS:
    1. Authentication & Ownership Isolation: Requires an authenticated session
       or JWT. Users can ONLY inspect and modify their own settings object,
       preventing cross-tenant / horizontal privilege escalation.
    2. Partial Merging with Strict Validation: Updates are validated through
       UserSettingsSerializer. Unauthorized keys are stripped.
    3. Key Masking on Read: Stored API keys are masked before serialization.
    --------------------------------------------------------------------------
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(format_safe_user_settings(request.user.settings or {}))

    def patch(self, request):
        serializer = UserSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        current_settings = request.user.settings or {}
        incoming = serializer.validated_data

        # Merge nested api_keys if provided so providers are updated individually.
        if "api_keys" in incoming and isinstance(current_settings.get("api_keys"), dict):
            incoming["api_keys"] = {**current_settings["api_keys"], **incoming["api_keys"]}

        request.user.settings = {**current_settings, **incoming}
        request.user.save(update_fields=["settings"])

        return Response(
            format_safe_user_settings(request.user.settings),
            status=status.HTTP_200_OK,
        )


class AuthConfigView(APIView):
    """Public flags the app needs before anyone signs in."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "allow_registration": settings.ALLOW_REGISTRATION,
                "require_login": settings.REQUIRE_LOGIN,
            }
        )


class RegisterView(APIView):
    """Register a new user with organization."""

    # The anonymous endpoints ignore any Authorization header, so a stale access token
    # left in the browser can't turn a sign-in into a 401.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.ALLOW_REGISTRATION:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)

        user_data = UserSerializer(user).data
        user_data["token"] = str(refresh.access_token)

        return Response(user_data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Authenticate user and return JWT tokens plus the user payload.

    Staff who have a passkey must use it: their password alone is refused.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                {"detail": "User account is disabled."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.is_staff and user.passkeys.exists():
            return Response(
                {
                    "detail": "Admin accounts sign in with a passkey.",
                    "code": "passkey_required",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(sign_in_payload(user, "pwd"), status=status.HTTP_200_OK)


class RefreshTokenView(APIView):
    """Refresh access token using refresh token.

    Refused for revoked (logged out) tokens and for users who were deactivated or deleted.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except (TokenError, AuthenticationFailed, ObjectDoesNotExist):
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {"access": serializer.validated_data["access"]},
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """Revoke the refresh token and end any admin session.

    The access token stays valid until it expires (JWT_ACCESS_TOKEN_LIFETIME_MINUTES).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass  # already expired or revoked
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)
