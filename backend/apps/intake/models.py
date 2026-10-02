"""Intake app models."""

from django.db import models


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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_request_type_display()} from {self.name} ({self.created_at:%Y-%m-%d})"
