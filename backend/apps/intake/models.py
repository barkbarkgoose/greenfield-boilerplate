"""Intake app models: vehicles, service requests and their message threads."""

import hashlib
import secrets

from django.conf import settings
from django.db import models


class Vehicle(models.Model):
    """A customer's car. Requests attach to it, so it builds a repair history."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vehicles"
    )
    vin = models.CharField(max_length=17)
    year = models.CharField(max_length=4, blank=True)
    make = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=60, blank=True)
    nickname = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "vin"], name="unique_vehicle_per_owner")
        ]

    def __str__(self) -> str:
        label = " ".join(part for part in (self.year, self.make, self.model) if part)
        return self.nickname or label or self.vin

    @classmethod
    def for_request(cls, owner, service_request: "ServiceRequest") -> "Vehicle | None":
        """Find or create the owner's vehicle for a request's VIN, filling blanks."""
        if not service_request.vin:
            return None
        vehicle, _ = cls.objects.get_or_create(owner=owner, vin=service_request.vin)
        changed = []
        for field, source in (
            ("year", "vehicle_year"),
            ("make", "vehicle_make"),
            ("model", "vehicle_model"),
        ):
            value = getattr(service_request, source)
            if value and not getattr(vehicle, field):
                setattr(vehicle, field, value)
                changed.append(field)
        if changed:
            vehicle.save(update_fields=changed)
        return vehicle


class PartsEstimate(models.Model):
    """An AI parts estimate, cached per vehicle + set of jobs.

    Requests for the same car and work reuse a recent row instead of calling
    the model again; see apps/intake/parts.py.
    """

    key = models.CharField(max_length=64, unique=True)
    vehicle = models.JSONField(default=dict)
    services = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    model_name = models.CharField(max_length=64, blank=True)
    generated_at = models.DateTimeField()

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self) -> str:
        return f"Parts estimate {self.key[:8]} ({self.generated_at:%Y-%m-%d})"


def hash_claim_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ServiceRequest(models.Model):
    """A booking request or a "please contact me" note from the public site."""

    class RequestType(models.TextChoices):
        BOOKING = "booking", "Booking"
        CALLBACK = "callback", "Contact me"

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        DECLINED = "declined", "Declined"

    request_type = models.CharField(
        max_length=16, choices=RequestType.choices, default=RequestType.BOOKING
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
    )

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    service_address = models.CharField(max_length=255, blank=True)

    vin = models.CharField(max_length=17, blank=True)
    vehicle_year = models.CharField(max_length=4, blank=True)
    vehicle_make = models.CharField(max_length=60, blank=True)
    vehicle_model = models.CharField(max_length=60, blank=True)

    services = models.JSONField(default=dict, blank=True, help_text="Service key -> quantity.")
    other_description = models.TextField(blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # Snapshot of the quote shown to the customer at submission time, so later
    # price changes don't rewrite what they were told.
    estimate = models.JSONField(default=dict, blank=True)
    estimated_total = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    is_emergency = models.BooleanField(default=False)

    # Filled in by the mechanic.
    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    odometer = models.PositiveIntegerField(null=True, blank=True)
    final_total = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    internal_notes = models.TextField(blank=True, help_text="Private; never shown to the customer.")

    class PartsStatus(models.TextChoices):
        NONE = "", "Not requested"
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        UNAVAILABLE = "unavailable", "Unavailable"

    parts_estimate = models.ForeignKey(
        PartsEstimate, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    parts_estimate_status = models.CharField(
        max_length=12, choices=PartsStatus.choices, blank=True, default=PartsStatus.NONE
    )

    # Lets a guest attach this request to an account later. Only the hash is
    # stored; the raw token goes to the submitter (screen + email) once.
    claim_token_hash = models.CharField(max_length=64, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_request_type_display()} from {self.name} ({self.created_at:%Y-%m-%d})"

    def issue_claim_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self.claim_token_hash = hash_claim_token(token)
        return token

    @property
    def vehicle_label(self) -> str:
        return " ".join(
            part for part in (self.vehicle_year, self.vehicle_make, self.vehicle_model) if part
        )


class RequestMessage(models.Model):
    """A note or question on a request, from the customer or the mechanic."""

    request = models.ForeignKey(
        ServiceRequest, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    from_staff = models.BooleanField(default=False)
    body = models.TextField(max_length=4000)
    # Set when the other side has seen it (staff for customer messages and
    # vice versa); drives the unread badges.
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        who = "Mechanic" if self.from_staff else "Customer"
        return f"{who} on #{self.request_id}: {self.body[:40]}"
