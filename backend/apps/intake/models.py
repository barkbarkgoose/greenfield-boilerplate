"""Intake app models: the delivery network (yards, stock, trucks) and orders.

Day-to-day facts that change often live here so staff can flip them from the
dashboard: which yard has which product, which trucks are running, and the
loads already booked. The slow-changing geography (which zip codes we serve
and how far each one is from each yard) lives in ``data/service_area.json``;
see service_area.py.
"""

import hashlib
import secrets
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models

from . import pricing

CENTS = Decimal("0.01")


# --- Delivery network -----------------------------------------------------------


class Yard(models.Model):
    """A place trucks load from. ``code`` is how the service-area file names it."""

    code = models.SlugField(max_length=32, unique=True, help_text="Matches the yard keys in data/service_area.json.")
    name = models.CharField(max_length=80)
    address = models.CharField(max_length=255, blank=True)
    # Optional; only used by `manage.py build_service_area` to estimate distances.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    active = models.BooleanField(default=True, help_text="Inactive yards are never routed to.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class YardStock(models.Model):
    """Whether a yard has a product right now. No row means it doesn't carry it."""

    yard = models.ForeignKey(Yard, on_delete=models.CASCADE, related_name="stock")
    product = models.CharField(max_length=32, choices=pricing.PRODUCT_CHOICES)
    in_stock = models.BooleanField(default=True)
    note = models.CharField(max_length=120, blank=True, help_text="e.g. Restock expected Friday")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["yard__name", "product"]
        constraints = [
            models.UniqueConstraint(fields=["yard", "product"], name="unique_stock_per_yard_product")
        ]

    def __str__(self) -> str:
        return f"{self.yard} / {self.product}: {'in stock' if self.in_stock else 'out'}"


class Truck(models.Model):
    """A dump truck. It loads at its home yard and works a day of ``workday_minutes``."""

    yard = models.ForeignKey(Yard, on_delete=models.PROTECT, related_name="trucks")
    name = models.CharField(max_length=60, help_text="e.g. Truck 3 (tandem)")
    capacity_yards = models.PositiveSmallIntegerField(help_text="Cubic yards per load.")
    workday_minutes = models.PositiveSmallIntegerField(
        default=600, help_text="Driving + loading time available per day."
    )
    active = models.BooleanField(default=True, help_text="Off = in the shop / not in service.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["yard__name", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.capacity_yards} yd, {self.yard})"


class TruckDayOff(models.Model):
    """A day a truck isn't available (maintenance, no driver...)."""

    truck = models.ForeignKey(Truck, on_delete=models.CASCADE, related_name="days_off")
    date = models.DateField()
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["truck", "date"], name="unique_truck_day_off")]

    def __str__(self) -> str:
        return f"{self.truck.name} off {self.date}"


# --- Orders -----------------------------------------------------------------------


def hash_claim_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Order(models.Model):
    """A delivery order, or a "please contact me" / special request."""

    class RequestType(models.TextChoices):
        DELIVERY = "delivery", "Delivery"
        CALLBACK = "callback", "Contact me / special request"

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        SCHEDULED = "scheduled", "Scheduled"
        DELIVERED = "delivered", "Delivered"
        DECLINED = "declined", "Declined"

    class Window(models.TextChoices):
        ANY = "any", "Any time"
        MORNING = "morning", "Morning"
        AFTERNOON = "afternoon", "Afternoon"

    class Coverage(models.TextChoices):
        """What the service-area table said about the zip at submission."""

        SERVE = "serve", "In our area"
        CONTACT = "contact", "Special request area"
        OUTSIDE = "outside", "Outside our area"
        UNKNOWN = "", "No zip given"

    class PlanStatus(models.TextChoices):
        """Whether dispatch could route every load (see dispatch.py)."""

        NONE = "", "Not planned"
        OK = "ok", "Routed"
        NO_CAPACITY = "no_capacity", "No truck available"
        OUT_OF_STOCK = "out_of_stock", "Out of stock"

    request_type = models.CharField(max_length=16, choices=RequestType.choices, default=RequestType.DELIVERY)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )

    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)
    zip_code = models.CharField(max_length=5, blank=True, db_index=True)

    items = models.JSONField(default=dict, blank=True, help_text="Product key -> cubic yards.")
    preferred_date = models.DateField(null=True, blank=True)
    delivery_window = models.CharField(max_length=12, choices=Window.choices, default=Window.ANY)
    placement_notes = models.TextField(blank=True, help_text="Where to dump it, access, gate codes...")
    notes = models.TextField(blank=True)

    # Language the customer used ("en" / "es"); their emails go out in it.
    language = models.CharField(max_length=8, default="en")

    # Snapshot of the quote shown at submission, so later price changes don't
    # rewrite what the customer was told.
    quote = models.JSONField(default=dict, blank=True)
    estimated_total = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    is_rush = models.BooleanField(default=False)
    coverage = models.CharField(max_length=10, choices=Coverage.choices, blank=True, default=Coverage.UNKNOWN)
    plan_status = models.CharField(max_length=16, choices=PlanStatus.choices, blank=True, default=PlanStatus.NONE)

    # Filled in by staff.
    scheduled_date = models.DateField(null=True, blank=True)
    delivered_on = models.DateField(null=True, blank=True)
    final_total = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    internal_notes = models.TextField(blank=True, help_text="Private; never shown to the customer.")

    # Consent from the form's checkboxes. ``contact_consent`` (calls/texts about
    # this order) is required to submit; ``marketing_consent`` is optional.
    # ``consent_version`` records which wording was agreed to (serializers.py).
    contact_consent = models.BooleanField(default=False)
    marketing_consent = models.BooleanField(default=False)
    consent_version = models.CharField(max_length=20, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)

    # Lets a guest attach this order to an account later. Only the hash is
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
    def delivery_date(self):
        """The confirmed date, else the one the customer asked for."""
        return self.scheduled_date or self.preferred_date

    @property
    def total_yards(self) -> int:
        return sum((self.items or {}).values())


class OrderLoad(models.Model):
    """One truckload of one product for an order, as routed by dispatch.py.

    Loads hold a truck's time on ``date`` (the order's delivery date), so the
    next customer's quote sees that truck as busier. ``yard``/``truck`` are
    blank when nothing was available; staff assign them by hand.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="loads")
    product = models.CharField(max_length=32, choices=pricing.PRODUCT_CHOICES)
    quantity = models.PositiveSmallIntegerField(help_text="Cubic yards.")
    yard = models.ForeignKey(Yard, on_delete=models.SET_NULL, null=True, blank=True, related_name="loads")
    truck = models.ForeignKey(Truck, on_delete=models.SET_NULL, null=True, blank=True, related_name="loads")
    date = models.DateField(null=True, blank=True, db_index=True)
    miles = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    minutes = models.PositiveSmallIntegerField(default=0, help_text="Truck time: loading, round trip, dumping.")
    sequence = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order_id", "sequence", "id"]

    def __str__(self) -> str:
        return f"#{self.order_id}: {self.quantity} yd {self.product} via {self.truck or 'unassigned'}"


class OrderMessage(models.Model):
    """A note or question on an order, from the customer or staff."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    from_staff = models.BooleanField(default=False)
    body = models.TextField(max_length=4000)
    # Set when the other side has seen it; drives the unread badges.
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        who = "Staff" if self.from_staff else "Customer"
        return f"{who} on #{self.order_id}: {self.body[:40]}"


class Invoice(models.Model):
    """The verified bill for an order: what was actually delivered.

    Staff build it from the delivered material and loads (repriced by
    ``pricing.quote``) plus their own lines for extra charges (e.g. spreading,
    a wait-time fee) and adjustments. Customers only see it once
    ``published_at`` is set; see invoicing.py.
    """

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="invoice")
    items = models.JSONField(default=dict, blank=True, help_text="Product key -> cubic yards.")
    # Delivered loads: [{product, quantity, miles}].
    loads = models.JSONField(default=list, blank=True)
    charge_rush_fee = models.BooleanField(default=False)
    # The material + delivery quote priced from ``items`` and ``loads``.
    priced = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, help_text="Shown to the customer.")
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Invoice for #{self.order_id}: ${self.total}"

    @property
    def is_published(self) -> bool:
        return self.published_at is not None


class InvoiceLine(models.Model):
    """One line staff add to an invoice: a service, a fee or an adjustment."""

    class Kind(models.TextChoices):
        SERVICE = "service", "Service"
        FEE = "fee", "Fee"
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
