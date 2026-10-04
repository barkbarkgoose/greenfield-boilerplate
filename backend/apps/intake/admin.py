"""Intake app admin. The day-to-day UI is the frontend dashboard; this is the fallback
and the place to set up yards and trucks."""

import csv

from django.contrib import admin
from django.http import HttpResponse

from .models import (
    Invoice,
    InvoiceLine,
    Order,
    OrderLoad,
    OrderMessage,
    Truck,
    TruckDayOff,
    Yard,
    YardStock,
)


class YardStockInline(admin.TabularInline):
    model = YardStock
    extra = 0
    fields = ["product", "in_stock", "note"]


class TruckInline(admin.TabularInline):
    model = Truck
    extra = 0
    fields = ["name", "capacity_yards", "workday_minutes", "active"]
    show_change_link = True


@admin.register(Yard)
class YardAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "address", "active"]
    list_editable = ["active"]
    search_fields = ["name", "code", "address"]
    inlines = [YardStockInline, TruckInline]


class TruckDayOffInline(admin.TabularInline):
    model = TruckDayOff
    extra = 1
    fields = ["date", "reason"]


@admin.register(Truck)
class TruckAdmin(admin.ModelAdmin):
    list_display = ["name", "yard", "capacity_yards", "workday_minutes", "active"]
    list_editable = ["active"]
    list_filter = ["yard", "active"]
    inlines = [TruckDayOffInline]


class OrderMessageInline(admin.TabularInline):
    model = OrderMessage
    extra = 0
    fields = ["created_at", "from_staff", "author", "body", "read_at"]
    readonly_fields = ["created_at"]


class OrderLoadInline(admin.TabularInline):
    model = OrderLoad
    extra = 0
    fields = ["product", "quantity", "yard", "truck", "date", "miles", "minutes"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "request_type",
        "status",
        "name",
        "phone",
        "zip_code",
        "preferred_date",
        "scheduled_date",
        "plan_status",
        "estimated_total",
    ]
    list_filter = ["status", "request_type", "plan_status", "coverage", "is_rush", "marketing_consent"]
    list_editable = ["status"]
    search_fields = ["name", "phone", "email", "zip_code", "delivery_address", "notes"]
    date_hierarchy = "created_at"
    raw_id_fields = ["customer"]
    readonly_fields = [
        "quote",
        "estimated_total",
        "is_rush",
        "coverage",
        "plan_status",
        "claim_token_hash",
        "contact_consent",
        "marketing_consent",
        "consent_version",
        "consent_at",
        "created_at",
        "updated_at",
    ]
    inlines = [OrderLoadInline, OrderMessageInline]
    actions = ["export_contacts"]

    @admin.action(description="Export contacts (CSV)")
    def export_contacts(self, request, queryset):
        """Name, phone, email and consent for the selected orders.

        For a promotions list, filter by "marketing consent: Yes" first.
        """
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="contacts.csv"'
        writer = csv.writer(response)
        writer.writerow(["name", "phone", "email", "zip_code", "language", "promotions_ok", "consent_at", "order_id"])
        for order in queryset.order_by("-created_at"):
            writer.writerow(
                [order.name, order.phone, order.email, order.zip_code, order.language,
                 "yes" if order.marketing_consent else "no", order.consent_at or "", order.id]
            )  # fmt: skip
        return response


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

    list_display = ["order", "total", "published_at", "updated_at"]
    readonly_fields = [
        "order", "items", "loads", "charge_rush_fee", "priced", "note", "total",
        "published_at", "created_at", "updated_at",
    ]  # fmt: skip
    inlines = [InvoiceLineInline]

    def has_add_permission(self, request):
        return False
