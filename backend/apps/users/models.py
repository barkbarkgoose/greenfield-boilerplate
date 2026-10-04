"""Users app models."""

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class UserManager(BaseUserManager):
    """Custom manager for User model."""

    def create_user(self, email, name, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    # Require a passkey to sign in (set in the Django admin or the shell). With no
    # passkey saved yet, the next password sign-in must create one before anything
    # else works. PASSKEYS_ENABLED=False switches the requirement off site-wide.
    passkey_required = models.BooleanField(
        default=False,
        help_text="Sign-in needs a passkey after the password. "
        "With none saved, the next sign-in sets one up.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email


class Passkey(models.Model):
    """A WebAuthn credential (e.g. saved in Bitwarden) registered to a user.

    Only the public key is stored. Passkeys belong to one domain and one
    database, so each environment (local, staging, production) has its own.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="passkeys")
    name = models.CharField(max_length=60)
    credential_id = models.CharField(max_length=512, unique=True, help_text="base64url")
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.user.email})"
