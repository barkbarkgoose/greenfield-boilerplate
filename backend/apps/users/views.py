"""Users app views."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.intake import notifications
from apps.intake.i18n import current_language

from .serializers import (
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .tokens import SessionEnded, issue_tokens, refresh_access

User = get_user_model()


class RegisterView(APIView):
    """Register a new customer account."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        tokens = issue_tokens(user)
        user_data = UserSerializer(user).data
        # "token" is the access token (kept for older clients); "refresh" renews it.
        user_data["token"] = tokens["access"]
        user_data["refresh"] = tokens["refresh"]

        return Response(user_data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """Authenticate user and return JWT tokens plus the user payload."""

    permission_classes = [AllowAny]
    throttle_scope = "auth_login"

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

        return Response(
            {**issue_tokens(user), "user": UserSerializer(user).data},
            status=status.HTTP_200_OK,
        )


class RefreshTokenView(APIView):
    """Renew the access token with the refresh token (until the session ends)."""

    permission_classes = [AllowAny]
    # A stale access token must not 401 the very call meant to replace it.
    authentication_classes: list = []

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            access = refresh_access(str(refresh_token))
        except SessionEnded:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response({"access": access}, status=status.HTTP_200_OK)


class PasswordResetRequestView(APIView):
    """Email a one-time link to choose a new password.

    Always answers the same way, so it can't be used to find out which emails
    have accounts. The link goes to the frontend (/reset-password/<uid>/<token>)
    and expires after PASSWORD_RESET_TIMEOUT.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"], is_active=True
        ).first()
        if user is not None and user.has_usable_password():
            language = current_language()
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            query = "" if language == "en" else f"?lang={language}"
            url = f"{settings.SITE_URL}/reset-password/{uid}/{token}{query}"
            notifications.notify_password_reset(user, url, language)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetConfirmView(APIView):
    """Set a new password from a reset link's uid and token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "password_reset_confirm"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["password"])
        user.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)
