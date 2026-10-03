"""Intake app admin. The day-to-day UI is the frontend dashboard; this is the fallback."""

from django.contrib import admin

from .models import PartsEstimate, RequestMessage, ServiceRequest, Vehicle


class RequestMessageInline(admin.TabularInline):
    model = RequestMessage
    extra = 0
    fields = ["created_at", "from_staff", "author", "body", "read_at"]
    readonly_fields = ["created_at"]


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "request_type",
        "status",
        "name",
        "phone",
        "email",
        "preferred_date",
        "scheduled_for",
        "is_emergency",
        "estimated_total",
    ]
    list_filter = ["status", "request_type", "is_emergency"]
    list_editable = ["status"]
    search_fields = ["name", "phone", "email", "vin", "notes"]
    date_hierarchy = "created_at"
    raw_id_fields = ["customer", "vehicle"]
    readonly_fields = [
        "estimate",
        "estimated_total",
        "is_emergency",
        "claim_token_hash",
        "parts_estimate",
        "parts_estimate_status",
        "created_at",
        "updated_at",
    ]
    inlines = [RequestMessageInline]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "vin", "owner", "created_at"]
    search_fields = ["vin", "make", "model", "owner__email"]
    raw_id_fields = ["owner"]


@admin.register(PartsEstimate)
class PartsEstimateAdmin(admin.ModelAdmin):
    list_display = ["__str__", "model_name", "generated_at"]
    readonly_fields = ["key", "vehicle", "services", "result", "model_name", "generated_at"]
