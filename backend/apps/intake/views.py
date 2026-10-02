"""Intake app views.

All endpoints are public: customers book without an account. Authentication is
disabled on them so a stale JWT left in the browser can't turn a booking into
a 401.
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import pricing
from .serializers import EstimateSerializer, ServiceRequestSerializer


class PublicAPIView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]


class CatalogView(PublicAPIView):
    def get(self, request):
        return Response(pricing.catalog())


class EstimateView(PublicAPIView):
    throttle_scope = "intake_estimate"

    def post(self, request):
        serializer = EstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantities = pricing.normalize_quantities(serializer.validated_data["services"])
        return Response(
            pricing.estimate(
                quantities,
                serializer.validated_data.get("preferred_date"),
                timezone.localdate(),
            )
        )


class ServiceRequestCreateView(PublicAPIView):
    throttle_scope = "intake_submit"

    def post(self, request):
        serializer = ServiceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service_request = serializer.save()
        data = ServiceRequestSerializer(service_request).data
        # Echo only what the confirmation screen needs.
        return Response(
            {
                "id": data["id"],
                "request_type": data["request_type"],
                "estimate": data["estimate"],
                "preferred_date": data["preferred_date"],
            },
            status=status.HTTP_201_CREATED,
        )
