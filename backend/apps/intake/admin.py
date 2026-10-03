"""Intake app admin. The day-to-day UI is the frontend dashboard; this is the fallback."""

from django.contrib import admin

from .models import Invoice, InvoiceLine, PartPriceExample, RequestMessage, ServiceRequest, Vehicle


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
        "parts_estimate_status",
        "parts_estimate_result",
        "created_at",
        "updated_at",
    ]
    inlines = [RequestMessageInline]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["__str__", "vin", "owner", "created_at"]
    search_fields = ["vin", "make", "model", "owner__email"]
    raw_id_fields = ["owner"]


@admin.register(PartPriceExample)
class PartPriceExampleAdmin(admin.ModelAdmin):
    """Your parts price table. Bulk edits: manage.py import_part_prices / export_part_prices."""

    list_display = [
        "service",
        "vehicle_type",
        "vehicle_make",
        "part_brand",
        "description",
        "source",
        "price",
        "updated_at",
    ]
    list_editable = ["price"]
    list_filter = ["service", "vehicle_type", "source"]
    search_fields = ["vehicle_make", "part_brand", "description", "source"]
    list_per_page = 100


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    fields = ["kind", "description", "quantity", "unit_price"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Read-only: edit invoices from the dashboard so totals are recalculated."""

    list_display = ["request", "total", "published_at", "updated_at"]
    readonly_fields = [
        "request", "services", "charge_rush_fee", "labor", "note", "total",
        "published_at", "created_at", "updated_at",
    ]  # fmt: skip
    inlines = [InvoiceLineInline]

    def has_add_permission(self, request):
        return False
