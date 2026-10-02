"""Intake app serializers."""

import re

from django.utils import timezone
from rest_framework import serializers

from . import pricing
from .models import ServiceRequest

# 17 characters, digits and capital letters except I, O and Q (ISO 3779).
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


class ServiceItemSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[s.key for s in pricing.SERVICES])
    quantity = serializers.IntegerField(min_value=1, required=False, default=1)

    def validate(self, attrs):
        service = pricing.SERVICES_BY_KEY[attrs["key"]]
        if attrs["quantity"] > service.max_quantity:
            raise serializers.ValidationError(
                {"quantity": f"{service.name} allows at most {service.max_quantity}."}
            )
        return attrs


def _validate_services(items):
    keys = [item["key"] for item in items]
    if len(keys) != len(set(keys)):
        raise serializers.ValidationError("Each service can only be listed once.")
    return items


def _validate_preferred_date(value):
    if value is not None and value < timezone.localdate():
        raise serializers.ValidationError("Pick a date that hasn't passed yet.")
    return value


class EstimateSerializer(serializers.Serializer):
    services = ServiceItemSerializer(many=True, allow_empty=True)
    preferred_date = serializers.DateField(required=False, allow_null=True)

    validate_services = staticmethod(_validate_services)
    validate_preferred_date = staticmethod(_validate_preferred_date)


class ServiceRequestSerializer(serializers.ModelSerializer):
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
            raise serializers.ValidationError(
                "A VIN is 17 letters and numbers (never I, O or Q)."
            )
        return vin

    def validate(self, attrs):
        errors = {}
        if not attrs.get("phone") and not attrs.get("email"):
            errors["phone"] = "Leave a phone number or email so I can reach you."

        services = attrs.get("services") or []
        if attrs.get("request_type", ServiceRequest.RequestType.BOOKING) == ServiceRequest.RequestType.BOOKING:
            if not attrs.get("vin"):
                errors["vin"] = "A VIN is needed so I can order the right parts."
            if not services:
                errors["services"] = "Pick at least one service."
            if not attrs.get("preferred_date"):
                errors["preferred_date"] = "Pick a preferred date."
            if any(s["key"] == "other" for s in services) and not attrs.get("other_description"):
                errors["other_description"] = "Tell me a bit about the other work."
        elif not attrs.get("notes"):
            errors["notes"] = "Leave a short note about what you need."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def create(self, validated_data):
        items = validated_data.pop("services", []) or []
        quantities = pricing.normalize_quantities(items)
        validated_data["services"] = quantities
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
