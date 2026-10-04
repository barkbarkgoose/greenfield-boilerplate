"""Intake app serializers."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from . import dispatch, invoicing, pricing, service_area
from .i18n import current_language, t
from .models import InvoiceLine, Order, OrderLoad, OrderMessage, Truck, TruckDayOff, YardStock

# Bump when the consent checkbox wording changes (frontend locales
# intake-consent__*), so each order records which wording was agreed to.
CONSENT_VERSION = "2026-10-04"


class ProductItemSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[p.key for p in pricing.PRODUCTS])
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        product = pricing.PRODUCTS_BY_KEY[attrs["key"]]
        if attrs["quantity"] < product.min_yards:
            raise serializers.ValidationError(
                {"quantity": t("validation__product--too-few", product=product.name, min=product.min_yards)}
            )
        if attrs["quantity"] > product.max_yards:
            raise serializers.ValidationError(
                {"quantity": t("validation__product--too-many", product=product.name, max=product.max_yards)}
            )
        return attrs


def _validate_items(items):
    keys = [item["key"] for item in items]
    if len(keys) != len(set(keys)):
        raise serializers.ValidationError(t("validation__products--duplicate"))
    return items


def _validate_delivery_date(value):
    if value is None:
        return value
    today = timezone.localdate()
    if value < today:
        raise serializers.ValidationError(t("validation__date--past"))
    if value > today + timedelta(days=pricing.MAX_DAYS_AHEAD):
        raise serializers.ValidationError(t("validation__date--too-far", days=pricing.MAX_DAYS_AHEAD))
    if not pricing.is_delivery_day(value):
        raise serializers.ValidationError(t("validation__date--no-delivery"))
    return value


def _validate_zip(value):
    if not value:
        return ""
    zip_code = service_area.normalize_zip(value)
    if not zip_code:
        raise serializers.ValidationError(t("validation__zip--invalid"))
    return zip_code


def price_order(quantities: dict[str, int], zip_code: str, day) -> tuple[dict, dispatch.Plan]:
    """Route and price an order. Returns (quote or {}, plan)."""
    result = dispatch.plan(quantities, zip_code, day)
    if not result.priceable:
        return {}, result
    quote = pricing.quote(quantities, dispatch.pricing_loads(result), day, timezone.localdate())
    return quote, result


class EstimateSerializer(serializers.Serializer):
    items = ProductItemSerializer(many=True, allow_empty=True)
    zip_code = serializers.CharField(required=False, allow_blank=True, default="")
    preferred_date = serializers.DateField(required=False, allow_null=True)

    validate_items = staticmethod(_validate_items)
    validate_zip_code = staticmethod(_validate_zip)
    validate_preferred_date = staticmethod(_validate_delivery_date)


class OrderSerializer(serializers.ModelSerializer):
    """Public order / contact form submission."""

    # Written as [{key, quantity}], stored as {key: yards}; see to_representation.
    items = ProductItemSerializer(many=True, required=False, allow_empty=True, write_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "request_type",
            "name",
            "phone",
            "email",
            "delivery_address",
            "zip_code",
            "items",
            "preferred_date",
            "delivery_window",
            "placement_notes",
            "notes",
            "contact_consent",
            "marketing_consent",
            "quote",
            "estimated_total",
            "is_rush",
            "created_at",
        ]
        read_only_fields = ["id", "quote", "estimated_total", "is_rush", "created_at"]

    validate_items = staticmethod(_validate_items)
    validate_zip_code = staticmethod(_validate_zip)
    validate_preferred_date = staticmethod(_validate_delivery_date)

    def validate(self, attrs):
        errors = {}
        if not (attrs.get("phone") or "").strip():
            errors["phone"] = t("validation__phone--required")
        if not attrs.get("contact_consent"):
            errors["contact_consent"] = t("validation__consent--required")

        if attrs.get("request_type", Order.RequestType.DELIVERY) == Order.RequestType.DELIVERY:
            if not attrs.get("items"):
                errors["items"] = t("validation__products--required")
            if not attrs.get("preferred_date"):
                errors["preferred_date"] = t("validation__date--required")
            if not (attrs.get("delivery_address") or "").strip():
                errors["delivery_address"] = t("validation__address--required")
            if not attrs.get("zip_code"):
                errors["zip_code"] = t("validation__zip--required")
            else:
                area = service_area.lookup(attrs["zip_code"])
                if area.status != service_area.SERVE:
                    # The form offers a special request for these instead.
                    errors["zip_code"] = t(f"validation__zip--{area.status}")
        elif not attrs.get("notes"):
            errors["notes"] = t("validation__notes--required")

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        items = validated_data.pop("items", []) or []
        quantities = pricing.normalize_quantities(items)
        validated_data["items"] = quantities
        validated_data["language"] = current_language()
        validated_data["consent_version"] = CONSENT_VERSION
        validated_data["consent_at"] = timezone.now()
        validated_data["coverage"] = (
            service_area.lookup(validated_data["zip_code"]).status if validated_data.get("zip_code") else ""
        )
        if validated_data.get("request_type", Order.RequestType.DELIVERY) == Order.RequestType.DELIVERY:
            quote, _ = price_order(quantities, validated_data["zip_code"], validated_data.get("preferred_date"))
            if quote:
                validated_data["quote"] = quote
                validated_data["estimated_total"] = quote["total"]
                validated_data["is_rush"] = quote["scheduling"]["is_rush"]
        return super().create(validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["items"] = [{"key": key, "quantity": qty} for key, qty in (instance.items or {}).items()]
        return data


# --- Customer & staff views ---------------------------------------------------


class MessageSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = OrderMessage
        fields = ["id", "body", "from_staff", "author_name", "created_at"]
        read_only_fields = ["id", "from_staff", "author_name", "created_at"]

    def get_author_name(self, obj):
        if obj.from_staff:
            return settings.BUSINESS_NAME
        return obj.author.name if obj.author else obj.order.name

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(t("validation__message--empty"))
        if len(value) > 4000:
            raise serializers.ValidationError(t("validation__message--too-long"))
        return value


class OrderSummarySerializer(serializers.ModelSerializer):
    """Compact row for lists."""

    items = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "request_type",
            "status",
            "zip_code",
            "city",
            "delivery_address",
            "items",
            "preferred_date",
            "scheduled_date",
            "delivery_window",
            "delivered_on",
            "estimated_total",
            "final_total",
            "is_rush",
            "unread_count",
            "created_at",
        ]

    def get_items(self, obj):
        return pricing.item_list(obj.items)

    def get_city(self, obj):
        return service_area.lookup(obj.zip_code).city if obj.zip_code else ""

    def get_unread_count(self, obj):
        # Annotated by the views: unread messages from the *other* side.
        return getattr(obj, "unread_count", 0)


class StaffOrderSummarySerializer(OrderSummarySerializer):
    class Meta(OrderSummarySerializer.Meta):
        fields = OrderSummarySerializer.Meta.fields + ["name", "phone", "plan_status", "coverage"]


class CustomerOrderSerializer(OrderSummarySerializer):
    messages = MessageSerializer(many=True, read_only=True)
    invoice = serializers.SerializerMethodField()
    messaging_enabled = serializers.SerializerMethodField()

    class Meta(OrderSummarySerializer.Meta):
        fields = OrderSummarySerializer.Meta.fields + [
            "name",
            "phone",
            "email",
            "placement_notes",
            "notes",
            "quote",
            "invoice",
            "messages",
            "messaging_enabled",
            "updated_at",
        ]

    def get_messaging_enabled(self, obj):
        return settings.INTAKE_MESSAGING_ENABLED

    def get_invoice(self, obj):
        """Customers only see an invoice once it's published."""
        invoice = invoicing.get_invoice(obj)
        return invoicing.invoice_payload(invoice) if invoice and invoice.is_published else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["quote"] = pricing.localize_quote(data.get("quote") or {})
        return data


class CustomerSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.EmailField()


class LoadSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField()
    yard_name = serializers.CharField(source="yard.name", default="", read_only=True)
    truck_name = serializers.CharField(source="truck.name", default="", read_only=True)

    class Meta:
        model = OrderLoad
        fields = [
            "id", "product", "product_name", "quantity", "yard", "yard_name",
            "truck", "truck_name", "date", "miles", "minutes",
        ]  # fmt: skip
        read_only_fields = fields

    def get_product_name(self, obj):
        product = pricing.PRODUCTS_BY_KEY.get(obj.product)
        return product.name if product else obj.product


class StaffOrderSerializer(CustomerOrderSerializer):
    customer = CustomerSummarySerializer(read_only=True)
    loads = LoadSerializer(many=True, read_only=True)
    admin_url = serializers.SerializerMethodField()
    customer_order_count = serializers.SerializerMethodField()
    area = serializers.SerializerMethodField()
    notify_customer = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta(CustomerOrderSerializer.Meta):
        fields = CustomerOrderSerializer.Meta.fields + [
            "customer",
            "customer_order_count",
            "internal_notes",
            "language",
            "coverage",
            "plan_status",
            "loads",
            "area",
            "contact_consent",
            "marketing_consent",
            "consent_at",
            "admin_url",
            "notify_customer",
        ]
        read_only_fields = [
            f
            for f in CustomerOrderSerializer.Meta.fields
            + [
                "customer", "updated_at", "invoice", "language", "coverage", "plan_status",
                "contact_consent", "marketing_consent", "consent_at",
            ]  # fmt: skip
            if f not in {"status", "scheduled_date", "delivery_window", "delivered_on", "final_total"}
        ]

    def get_admin_url(self, obj):
        """Where the Django admin lives (ADMIN_URL), for links to yards and trucks."""
        return f"/{settings.ADMIN_URL}"

    def get_customer_order_count(self, obj):
        """How many orders this person has made: a quick repeat-customer signal."""
        if obj.customer_id:
            return obj.customer.orders.count()
        if obj.email:
            return Order.objects.filter(email__iexact=obj.email).count()
        return 1

    def get_area(self, obj):
        """What the service-area table says about the zip, with every yard's distance."""
        area = service_area.lookup(obj.zip_code)
        return {
            "status": area.status,
            "city": area.city,
            "note": area.note,
            "yards": [{"code": y.code, "miles": str(y.miles), "minutes": y.minutes} for y in area.yards],
        }

    def get_invoice(self, obj):
        """Staff see the invoice draft too."""
        invoice = invoicing.get_invoice(obj)
        return invoicing.invoice_payload(invoice) if invoice else None

    def validate_scheduled_date(self, value):
        if value is not None and not pricing.is_delivery_day(value):
            raise serializers.ValidationError(t("validation__date--no-delivery"))
        return value

    def validate(self, attrs):
        status = attrs.get("status", self.instance.status if self.instance else None)
        scheduled = attrs.get("scheduled_date", self.instance.scheduled_date if self.instance else None)
        if status == Order.Status.SCHEDULED and not scheduled:
            raise serializers.ValidationError({"scheduled_date": t("validation__schedule--date-required")})
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop("notify_customer", None)
        invoice = invoicing.get_invoice(instance)
        if invoice and invoice.is_published:
            # A published invoice sets the final total.
            validated_data.pop("final_total", None)
        if (
            validated_data.get("status") == Order.Status.DELIVERED
            and not validated_data.get("delivered_on")
            and not instance.delivered_on
        ):
            validated_data["delivered_on"] = timezone.localdate()
        return super().update(instance, validated_data)


class LoadAssignmentSerializer(serializers.Serializer):
    truck = serializers.PrimaryKeyRelatedField(queryset=Truck.objects.select_related("yard"), allow_null=True)


class StockUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = YardStock
        fields = ["id", "in_stock", "note"]


class TruckUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Truck
        fields = ["id", "active"]


class DayOffSerializer(serializers.ModelSerializer):
    class Meta:
        model = TruckDayOff
        fields = ["date", "reason"]


# --- Invoices ------------------------------------------------------------------

MAX_INVOICE_LINES = 60
MAX_INVOICE_LOADS = 40


class InvoiceLineSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=InvoiceLine.Kind.choices)
    description = serializers.CharField(max_length=200)
    quantity = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.01"))
    unit_price = serializers.DecimalField(max_digits=8, decimal_places=2)

    def validate(self, attrs):
        if attrs["unit_price"] < 0 and attrs["kind"] != InvoiceLine.Kind.ADJUSTMENT:
            raise serializers.ValidationError({"unit_price": t("validation__invoice-line--negative")})
        return attrs


class InvoiceLoadSerializer(serializers.Serializer):
    product = serializers.ChoiceField(choices=[p.key for p in pricing.PRODUCTS])
    quantity = serializers.IntegerField(min_value=1, max_value=60)
    miles = serializers.DecimalField(max_digits=6, decimal_places=1, min_value=Decimal("0"))


class InvoiceSerializer(serializers.Serializer):
    """Staff input for an invoice; the whole invoice is sent on every save."""

    items = serializers.ListField(child=serializers.DictField(), allow_empty=True)
    loads = InvoiceLoadSerializer(many=True, allow_empty=True)
    charge_rush_fee = serializers.BooleanField(default=False)
    lines = InvoiceLineSerializer(many=True, allow_empty=True)
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")
    published = serializers.BooleanField(default=False)
    notify_customer = serializers.BooleanField(default=False)

    def validate_items(self, value):
        # Invoices record what was delivered, so the order form's minimums
        # don't apply: any whole number of yards from 1 up.
        serializer = InvoiceItemSerializer(data=value, many=True)
        serializer.is_valid(raise_exception=True)
        return _validate_items(serializer.validated_data)

    def validate_loads(self, value):
        if len(value) > MAX_INVOICE_LOADS:
            raise serializers.ValidationError(t("validation__invoice--too-many-loads", max=MAX_INVOICE_LOADS))
        return value

    def validate_lines(self, value):
        if len(value) > MAX_INVOICE_LINES:
            raise serializers.ValidationError(t("validation__invoice--too-many-lines", max=MAX_INVOICE_LINES))
        return value


class InvoiceItemSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[p.key for p in pricing.PRODUCTS])
    quantity = serializers.IntegerField(min_value=1, max_value=200)
