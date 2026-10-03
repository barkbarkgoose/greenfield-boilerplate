"""Intake app models: vehicles, service requests and their message threads."""

import hashlib
import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models

from . import pricing

CENTS = Decimal("0.01")


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


class VehicleType(models.TextChoices):
    SEDAN = "sedan", "Sedan / car"
    CROSSOVER = "crossover", "Crossover"
    SUV = "suv", "SUV / van"
    TRUCK = "truck", "Truck"
    EUROPEAN = "european", "European"


class PartPriceExample(models.Model):
    """One real parts price you found, used to estimate parts for similar cars.

    ``price`` is the parts cost for one unit of the job: one axle for brake and
    suspension work, the whole job otherwise (e.g. oil + filter). Estimates take
    the min / median / max of the examples that match a vehicle; see parts.py.
    """

    service = models.CharField(
        max_length=32,
        choices=[(s.key, s.name) for s in pricing.SERVICES if not s.quote_required],
    )
    vehicle_type = models.CharField(max_length=16, choices=VehicleType.choices)
    vehicle_make = models.CharField(
        max_length=40, blank=True, help_text="Optional, e.g. TOYOTA. Blank = any make of this type."
    )
    part_brand = models.CharField(max_length=60, blank=True, help_text="e.g. Duralast Gold, Akebono")
    description = models.CharField(max_length=120, blank=True, help_text="e.g. Ceramic pads, 2018 Camry front")
    source = models.CharField(max_length=40, blank=True, help_text="e.g. AutoZone, RockAuto")
    source_url = models.URLField(max_length=500, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service", "vehicle_type", "vehicle_make", "price"]
        indexes = [models.Index(fields=["service", "vehicle_type"])]

    def __str__(self) -> str:
        who = self.vehicle_make or self.get_vehicle_type_display()
        return f"{self.service} / {who}: ${self.price}"

    def save(self, *args, **kwargs):
        self.vehicle_make = self.vehicle_make.strip().upper()
        super().save(*args, **kwargs)


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

    # Language the customer used ("en" / "es"); their emails go out in it.
    language = models.CharField(max_length=8, default="en")

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

    # Vehicle type used for parts matching: detected from the VIN, editable by staff.
    vehicle_type = models.CharField(max_length=16, choices=VehicleType.choices, blank=True)
    # Snapshot of the parts estimate shown to the customer (like ``estimate``).
    parts_estimate_result = models.JSONField(default=dict, blank=True)
    parts_estimate_status = models.CharField(
        max_length=12, choices=PartsStatus.choices, blank=True, default=PartsStatus.NONE
    )

    # Consent from the form's checkboxes. ``contact_consent`` (calls/texts about
    # this request) is required to submit; ``marketing_consent`` (occasional
    # promotions by text/email) is optional. ``consent_version`` records which
    # checkbox wording they agreed to (``CONSENT_VERSION`` in serializers.py).
    contact_consent = models.BooleanField(default=False)
    marketing_consent = models.BooleanField(default=False)
    consent_version = models.CharField(max_length=20, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)

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


class Invoice(models.Model):
    """The verified bill for a request: the work actually done and real parts cost.

    Staff build it from the requested jobs (repriced by ``pricing.estimate``,
    so bundles and deals still apply) plus their own lines for parts at cost,
    shipping, extra labor and adjustments. Customers only see it once
    ``published_at`` is set; see invoicing.py.
    """

    request = models.OneToOneField(
        ServiceRequest, on_delete=models.CASCADE, related_name="invoice"
    )
    services = models.JSONField(default=dict, blank=True, help_text="Service key -> quantity.")
    charge_rush_fee = models.BooleanField(default=False)
    # Labor priced from ``services`` (same shape as ServiceRequest.estimate).
    labor = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, help_text="Shown to the customer.")
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Invoice for #{self.request_id}: ${self.total}"

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


class InvoiceLine(models.Model):
    """One line staff add to an invoice: a part, shipping, extra labor or an adjustment."""

    class Kind(models.TextChoices):
        PART = "part", "Part"
        SHIPPING = "shipping", "Shipping"
        LABOR = "labor", "Extra labor"
        ADJUSTMENT = "adjustment", "Adjustment"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    # Negative only for adjustments (e.g. a discount).
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.description}"

    @property
    def amount(self):
        return (self.quantity * self.unit_price).quantize(CENTS, rounding=ROUND_HALF_UP)
