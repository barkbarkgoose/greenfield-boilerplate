"""Intake app serializers."""

import re

from django.utils import timezone
from rest_framework import serializers

from . import parts, pricing
from .i18n import current_language, t
from .models import RequestMessage, ServiceRequest, Vehicle, VehicleType

# 17 characters, digits and capital letters except I, O and Q (ISO 3779).
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def service_list(services: dict) -> list[dict]:
    """Stored ``{key: qty}`` -> ``[{key, name, quantity}]`` in catalog order."""
    services = services or {}
    return [
        {"key": s.key, "name": s.name, "quantity": services[s.key]}
        for s in pricing.SERVICES
        if s.key in services
    ]


class ServiceItemSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[s.key for s in pricing.SERVICES])
    quantity = serializers.IntegerField(min_value=1, required=False, default=1)

    def validate(self, attrs):
        service = pricing.SERVICES_BY_KEY[attrs["key"]]
        if attrs["quantity"] > service.max_quantity:
            raise serializers.ValidationError(
                {"quantity": t("validation__service--too-many", service=service.name, max=service.max_quantity)}
            )
        return attrs


def _validate_services(items):
    keys = [item["key"] for item in items]
    if len(keys) != len(set(keys)):
        raise serializers.ValidationError(t("validation__services--duplicate"))
    return items


def _validate_preferred_date(value):
    if value is not None and value < timezone.localdate():
        raise serializers.ValidationError(t("validation__date--past"))
    return value


class EstimateSerializer(serializers.Serializer):
    services = ServiceItemSerializer(many=True, allow_empty=True)
    preferred_date = serializers.DateField(required=False, allow_null=True)
    # Optional: the customer's own guess at their vehicle class, so the parts
    # estimate preview doesn't need a VIN decode before submission.
    vehicle_type = serializers.ChoiceField(
        choices=VehicleType.choices, required=False, allow_blank=True, default=""
    )

    validate_services = staticmethod(_validate_services)
    validate_preferred_date = staticmethod(_validate_preferred_date)


class ServiceRequestSerializer(serializers.ModelSerializer):
    """Public booking / contact form submission."""

    # Written as [{key, quantity}], stored as {key: quantity}; see to_representation.
    services = ServiceItemSerializer(
        many=True, required=False, allow_empty=True, write_only=True
    )

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_type",
            "name",
            "phone",
            "email",
            "service_address",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "vehicle_type",
            "services",
            "other_description",
            "preferred_date",
            "notes",
            "estimate",
            "estimated_total",
            "is_emergency",
            "created_at",
        ]
        read_only_fields = ["id", "estimate", "estimated_total", "is_emergency", "created_at"]

    validate_services = staticmethod(_validate_services)
    validate_preferred_date = staticmethod(_validate_preferred_date)

    def validate_vin(self, value):
        vin = re.sub(r"[\s-]", "", value or "").upper()
        if vin and not VIN_RE.match(vin):
            raise serializers.ValidationError(t("validation__vin--invalid"))
        return vin

    def validate(self, attrs):
        errors = {}
        if not attrs.get("phone") and not attrs.get("email"):
            errors["phone"] = t("validation__contact--required")

        services = attrs.get("services") or []
        if attrs.get("request_type", ServiceRequest.RequestType.BOOKING) == ServiceRequest.RequestType.BOOKING:
            if not attrs.get("vin"):
                errors["vin"] = t("validation__vin--required")
            if not services:
                errors["services"] = t("validation__services--required")
            if not attrs.get("preferred_date"):
                errors["preferred_date"] = t("validation__date--required")
            if any(s["key"] == "other" for s in services) and not attrs.get("other_description"):
                errors["other_description"] = t("validation__other--required")
        elif not attrs.get("notes"):
            errors["notes"] = t("validation__notes--required")

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        items = validated_data.pop("services", []) or []
        quantities = pricing.normalize_quantities(items)
        validated_data["services"] = quantities
        validated_data["language"] = current_language()
        if quantities:
            quote = pricing.estimate(
                quantities, validated_data.get("preferred_date"), timezone.localdate()
            )
            validated_data["estimate"] = quote
            validated_data["estimated_total"] = quote["total"]
            validated_data["is_emergency"] = quote["scheduling"]["is_emergency"]
        return super().create(validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["services"] = [
            {"key": key, "quantity": qty} for key, qty in (instance.services or {}).items()
        ]
        return data


# --- Customer & staff views ---------------------------------------------------


class MessageSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = RequestMessage
        fields = ["id", "body", "from_staff", "author_name", "created_at"]
        read_only_fields = ["id", "from_staff", "author_name", "created_at"]

    def get_author_name(self, obj):
        if obj.from_staff:
            return "Mechanic"
        return obj.author.name if obj.author else obj.request.name

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(t("validation__message--empty"))
        if len(value) > 4000:
            raise serializers.ValidationError(t("validation__message--too-long"))
        return value


class VehicleSummarySerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = Vehicle
        fields = ["id", "vin", "year", "make", "model", "nickname", "label"]


class RequestSummarySerializer(serializers.ModelSerializer):
    """Compact row for lists and vehicle history."""

    services = serializers.SerializerMethodField()
    vehicle_label = serializers.CharField(read_only=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "request_type",
            "status",
            "vehicle_id",
            "vehicle_label",
            "vin",
            "services",
            "preferred_date",
            "scheduled_for",
            "completed_on",
            "odometer",
            "estimated_total",
            "final_total",
            "is_emergency",
            "unread_count",
            "created_at",
        ]

    def get_services(self, obj):
        return service_list(obj.services)

    def get_unread_count(self, obj):
        # Annotated by the views: unread messages from the *other* side.
        return getattr(obj, "unread_count", 0)


class StaffRequestSummarySerializer(RequestSummarySerializer):
    class Meta(RequestSummarySerializer.Meta):
        fields = RequestSummarySerializer.Meta.fields + ["name", "phone"]


class CustomerRequestSerializer(RequestSummarySerializer):
    messages = MessageSerializer(many=True, read_only=True)
    vehicle = VehicleSummarySerializer(read_only=True)
    parts_estimate = serializers.SerializerMethodField()

    class Meta(RequestSummarySerializer.Meta):
        fields = RequestSummarySerializer.Meta.fields + [
            "vehicle",
            "name",
            "phone",
            "email",
            "service_address",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "other_description",
            "notes",
            "estimate",
            "parts_estimate",
            "messages",
        ]

    def get_parts_estimate(self, obj):
        return parts.as_payload(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["estimate"] = pricing.localize_estimate(data.get("estimate") or {})
        return data


class VehicleSerializer(VehicleSummarySerializer):
    history = serializers.SerializerMethodField()

    class Meta(VehicleSummarySerializer.Meta):
        fields = VehicleSummarySerializer.Meta.fields + ["history", "created_at"]
        read_only_fields = ["vin", "year", "make", "model", "created_at"]

    def get_history(self, obj):
        return RequestSummarySerializer(obj.service_requests.all(), many=True).data


class CustomerSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.EmailField()


class StaffRequestSerializer(CustomerRequestSerializer):
    customer = CustomerSummarySerializer(read_only=True)
    customer_request_count = serializers.SerializerMethodField()
    notify_customer = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta(CustomerRequestSerializer.Meta):
        fields = CustomerRequestSerializer.Meta.fields + [
            "customer",
            "customer_request_count",
            "internal_notes",
            "vehicle_type",
            "language",
            "updated_at",
            "notify_customer",
        ]
        read_only_fields = [
            f
            for f in CustomerRequestSerializer.Meta.fields
            + ["customer", "updated_at", "parts_estimate", "language"]
            if f not in {"status", "scheduled_for", "completed_on", "odometer", "final_total"}
        ]

    def get_customer_request_count(self, obj):
        """How many requests this person has made: a quick repeat-customer signal."""
        if obj.customer_id:
            return obj.customer.service_requests.count()
        if obj.email:
            return ServiceRequest.objects.filter(email__iexact=obj.email).count()
        return 1

    def validate(self, attrs):
        status = attrs.get("status", self.instance.status if self.instance else None)
        scheduled_for = attrs.get(
            "scheduled_for", self.instance.scheduled_for if self.instance else None
        )
        if status == ServiceRequest.Status.SCHEDULED and not scheduled_for:
            raise serializers.ValidationError(
                {"scheduled_for": t("validation__schedule--time-required")}
            )
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop("notify_customer", None)
        if (
            validated_data.get("status") == ServiceRequest.Status.COMPLETED
            and not validated_data.get("completed_on")
            and not instance.completed_on
        ):
            validated_data["completed_on"] = timezone.localdate()
        return super().update(instance, validated_data)
