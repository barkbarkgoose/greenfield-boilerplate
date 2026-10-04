"""Users app views."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.intake import notifications
from apps.intake.i18n import current_language

from . import passkeys
from .models import Passkey
from .serializers import (
    LoginSerializer,
    PasskeySerializer,
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

        if passkeys.requirement_applies(user):
            if user.passkeys.exists():
                # Step 2: no tokens until a saved passkey signs the challenge.
                return Response({"passkey_required": True, **passkeys.authentication_options(user)})
            # First sign-in since the requirement was set: this session can
            # only save a passkey (then gets a normal one).
            return Response(
                {
                    **issue_tokens(user, passkey_setup=True),
                    "user": UserSerializer(user).data,
                    "passkey_setup_required": True,
                }
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


# --- Passkeys (see passkeys.py) --------------------------------------------------


def _passkey_error(error: passkeys.PasskeyError) -> Response:
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class PasskeyLoginView(APIView):
    """Step 2 of signing in when a passkey is required: verify it, issue tokens."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "auth_login"

    def post(self, request):
        try:
            user = passkeys.authenticate(
                request.data.get("challenge_token", ""), request.data.get("credential") or {}
            )
        except passkeys.PasskeyError as error:
            return _passkey_error(error)
        return Response({**issue_tokens(user), "user": UserSerializer(user).data})


class PasskeyListView(APIView):
    """The signed-in user's passkeys, and whether their account requires one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "required": passkeys.requirement_applies(request.user),
                "passkeys": PasskeySerializer(request.user.passkeys.all(), many=True).data,
            }
        )


class PasskeyRegisterOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(passkeys.registration_options(request.user))


class PasskeyRegisterView(APIView):
    """Save a new passkey. Returns a fresh, unrestricted session."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            passkey = passkeys.register(
                request.user,
                request.data.get("challenge_token", ""),
                request.data.get("credential") or {},
                request.data.get("name", ""),
            )
        except passkeys.PasskeyError as error:
            return _passkey_error(error)
        return Response(
            {"passkey": PasskeySerializer(passkey).data, **issue_tokens(request.user)},
            status=status.HTTP_201_CREATED,
        )


class PasskeyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        passkey = Passkey.objects.filter(pk=pk, user=request.user).first()
        if passkey is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        # Removing the last one would reopen "save one on next sign-in" to
        # anyone with just the password, so that takes reset_passkeys.
        if passkeys.requirement_applies(request.user) and request.user.passkeys.count() == 1:
            return Response(
                {"detail": "Your account requires a passkey, so the last one can't be removed. Add another first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        passkey.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
