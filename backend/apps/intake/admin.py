"""Intake app admin: where incoming requests are reviewed."""

from django.contrib import admin

from .models import ServiceRequest


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
        "is_emergency",
        "estimated_total",
    ]
    list_filter = ["status", "request_type", "is_emergency"]
    list_editable = ["status"]
    search_fields = ["name", "phone", "email", "vin", "notes"]
    date_hierarchy = "created_at"
    readonly_fields = ["estimate", "estimated_total", "is_emergency", "created_at", "updated_at"]
