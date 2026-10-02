"""Intake app views.

* Public: catalog, estimate and the booking/contact form. No login needed.
* Customer ("my garage"): a signed-in customer's vehicles, requests and notes.
* Staff: the mechanic's dashboard for managing every request.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import notifications, pricing
from .authentication import OptionalJWTAuthentication
from .captcha import check_human
from .models import RequestMessage, ServiceRequest, Vehicle, hash_claim_token
from .serializers import (
    CustomerRequestSerializer,
    EstimateSerializer,
    MessageSerializer,
    RequestSummarySerializer,
    ServiceRequestSerializer,
    StaffRequestSerializer,
    StaffRequestSummarySerializer,
    VehicleSerializer,
)


def _unread(from_staff: bool) -> Count:
    """Count unread messages written by the given side."""
    return Count(
        "messages",
        filter=Q(messages__from_staff=from_staff, messages__read_at__isnull=True),
        distinct=True,
    )


def _mark_read(service_request: ServiceRequest, from_staff: bool) -> None:
    service_request.messages.filter(from_staff=from_staff, read_at__isnull=True).update(
        read_at=timezone.now()
    )


# --- Public --------------------------------------------------------------------


class PublicAPIView(APIView):
    # No authentication: a stale JWT left in the browser can't 401 these.
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


class ServiceRequestCreateView(APIView):
    """Booking or contact form. Signed-in customers get it filed to their garage."""

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_scope = "intake_submit"

    def post(self, request):
        user = request.user if request.user.is_authenticated else None
        if user is None:
            check_human(request)

        serializer = ServiceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        claim_token = None
        with transaction.atomic():
            service_request = serializer.save(customer=user)
            if user is not None:
                service_request.vehicle = Vehicle.for_request(user, service_request)
            else:
                claim_token = service_request.issue_claim_token()
            service_request.save(update_fields=["vehicle", "claim_token_hash"])
            transaction.on_commit(
                lambda: notifications.notify_new_request(service_request, claim_token)
            )

        return Response(
            {
                "id": service_request.id,
                "request_type": service_request.request_type,
                "estimate": service_request.estimate,
                "preferred_date": service_request.preferred_date,
                # Lets a guest attach this request to an account right away.
                "claim_token": claim_token,
            },
            status=status.HTTP_201_CREATED,
        )


# --- Customer ------------------------------------------------------------------


class MyVehiclesView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = VehicleSerializer
    pagination_class = None

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user).prefetch_related(
            "service_requests"
        )


class MyVehicleDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = VehicleSerializer
    http_method_names = ["get", "patch"]

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user)


class MyRequestsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RequestSummarySerializer
    pagination_class = None

    def get_queryset(self):
        return ServiceRequest.objects.filter(customer=self.request.user).annotate(
            unread_count=_unread(from_staff=True)
        )


class MyRequestDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerRequestSerializer

    def get_queryset(self):
        return ServiceRequest.objects.filter(customer=self.request.user).select_related(
            "vehicle"
        ).prefetch_related("messages__author")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _mark_read(instance, from_staff=True)
        return Response(self.get_serializer(instance).data)


class MyRequestMessageView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "intake_message"

    def post(self, request, pk):
        service_request = get_object_or_404(ServiceRequest, pk=pk, customer=request.user)
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(request=service_request, author=request.user, from_staff=False)
        transaction.on_commit(lambda: notifications.notify_customer_message(message))
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ClaimRequestView(APIView):
    """Attach a guest request to the signed-in account using its emailed token."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "intake_claim"

    def post(self, request):
        token = str(request.data.get("token") or "")
        service_request = (
            ServiceRequest.objects.filter(claim_token_hash=hash_claim_token(token)).first()
            if token
            else None
        )
        if service_request is None:
            return Response(
                {"detail": "That link is invalid or has already been used."},
                status=status.HTTP_404_NOT_FOUND,
            )
        with transaction.atomic():
            service_request.customer = request.user
            service_request.vehicle = Vehicle.for_request(request.user, service_request)
            service_request.claim_token_hash = ""
            service_request.save(update_fields=["customer", "vehicle", "claim_token_hash"])
        return Response({"id": service_request.id})


# --- Staff ---------------------------------------------------------------------


class StaffSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        counts = dict(
            ServiceRequest.objects.values_list("status").annotate(n=Count("id")).order_by()
        )
        upcoming = ServiceRequest.objects.filter(
            status=ServiceRequest.Status.SCHEDULED,
            scheduled_for__gte=now - timedelta(hours=12),
            scheduled_for__lte=now + timedelta(days=14),
        ).order_by("scheduled_for")[:10]
        return Response(
            {
                "status_counts": {s: counts.get(s, 0) for s in ServiceRequest.Status.values},
                "unread_messages": RequestMessage.objects.filter(
                    from_staff=False, read_at__isnull=True
                ).count(),
                "new_this_week": ServiceRequest.objects.filter(
                    created_at__gte=now - timedelta(days=7)
                ).count(),
                "emergencies_open": ServiceRequest.objects.filter(
                    is_emergency=True,
                    status__in=[ServiceRequest.Status.NEW, ServiceRequest.Status.CONTACTED],
                ).count(),
                "upcoming": StaffRequestSummarySerializer(upcoming, many=True).data,
            }
        )


class StaffRequestListView(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = StaffRequestSummarySerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = ServiceRequest.objects.annotate(unread_count=_unread(from_staff=False))
        if status_filter := params.get("status"):
            qs = qs.filter(status__in=status_filter.split(","))
        if request_type := params.get("request_type"):
            qs = qs.filter(request_type=request_type)
        if params.get("emergency") == "1":
            qs = qs.filter(is_emergency=True)
        if params.get("unread") == "1":
            qs = qs.filter(unread_count__gt=0)
        if search := params.get("q", "").strip():
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(vin__icontains=search)
                | Q(vehicle_make__icontains=search)
                | Q(vehicle_model__icontains=search)
            )
        ordering = {
            "newest": ["-created_at"],
            "oldest": ["created_at"],
            "preferred": ["preferred_date", "created_at"],
            "scheduled": ["scheduled_for", "created_at"],
        }.get(params.get("ordering", "newest"), ["-created_at"])
        return qs.order_by(*ordering)


class StaffRequestDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = StaffRequestSerializer
    http_method_names = ["get", "patch"]
    queryset = ServiceRequest.objects.select_related("vehicle", "customer").prefetch_related(
        "messages__author"
    )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _mark_read(instance, from_staff=False)
        return Response(self.get_serializer(instance).data)

    def perform_update(self, serializer):
        before = (serializer.instance.status, serializer.instance.scheduled_for)
        notify = serializer.validated_data.get("notify_customer", False)
        instance = serializer.save()
        if notify and (instance.status, instance.scheduled_for) != before:
            transaction.on_commit(lambda: notifications.notify_status_change(instance))


class StaffRequestMessageView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        service_request = get_object_or_404(ServiceRequest, pk=pk)
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(request=service_request, author=request.user, from_staff=True)
        transaction.on_commit(lambda: notifications.notify_staff_reply(message))
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)
