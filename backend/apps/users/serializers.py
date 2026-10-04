"""Users app serializers."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from apps.intake.i18n import t

from .models import Passkey

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""

    passkey_required = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "is_staff", "passkey_required"]
        read_only_fields = ["is_staff"]

    def get_passkey_required(self, obj):
        return bool(settings.PASSKEYS_ENABLED and obj.passkey_required)


class PasskeySerializer(serializers.ModelSerializer):
    class Meta:
        model = Passkey
        fields = ["id", "name", "created_at", "last_used_at"]


class RegisterSerializer(serializers.Serializer):
    """Serializer for user registration."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    name = serializers.CharField(max_length=255)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(t("validation__register--email-taken"))
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            name=validated_data["name"],
            password=validated_data["password"],
        )
        return user


class LoginSerializer(serializers.Serializer):
    """Serializer for user login."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """A new password plus the uid/token from the emailed reset link."""

    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            user = None
        # Tokens are tied to the current password hash, so a link stops working
        # once it's been used (or the password changed some other way).
        if user is None or not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": t("validation__password-reset--invalid")})
        try:
            validate_password(attrs["password"], user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": list(error.messages)}) from error
        attrs["user"] = user
        return attrs
