"""Passkeys (WebAuthn credentials) and the one-time challenges used to create and use them."""

import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

CHALLENGE_TTL = timedelta(minutes=5)


class Passkey(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkeys"
    )
    name = models.CharField(max_length=100)
    # base64url, as the browser sends it back on sign-in
    credential_id = models.CharField(max_length=1400, unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    # the hostname (or parent domain) it was created for; it only works there
    rp_id = models.CharField(max_length=255)
    # synced by a password manager or platform account, rather than bound to one device
    backed_up = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.name} ({self.user})"


class PasskeyChallenge(models.Model):
    """A random challenge handed to the browser by a begin step, consumed once by the
    matching finish step. Stored in the database so it works across gunicorn workers."""

    REGISTER = "register"
    SIGN_IN = "sign_in"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purpose = models.CharField(max_length=10)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )
    challenge = models.BinaryField()
    rp_id = models.CharField(max_length=255)
    origin = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def purge_expired(cls) -> None:
        cls.objects.filter(created_at__lt=timezone.now() - CHALLENGE_TTL).delete()

    @classmethod
    def take(cls, challenge_id, purpose: str, user=None) -> "PasskeyChallenge | None":
        """Return the challenge and delete it, or None if it is unknown, used or expired."""
        try:
            challenge = cls.objects.get(pk=challenge_id, purpose=purpose, user=user)
        except (cls.DoesNotExist, ValidationError, ValueError, TypeError):
            return None
        # delete() reports 0 when a concurrent request already took it
        if cls.objects.filter(pk=challenge.pk).delete()[0] == 0:
            return None
        if challenge.created_at < timezone.now() - CHALLENGE_TTL:
            return None
        return challenge
