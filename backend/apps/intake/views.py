"""Intake app views.

* Public: catalog, live quote and the order/contact form. No login needed.
* Customer ("my orders"): a signed-in customer's orders and notes.
* Staff: the order dashboard plus the dispatch board (trucks, loads, stock).
"""

from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import dispatch, invoicing, notifications, pricing
from .authentication import OptionalJWTAuthentication
from .captcha import check_human
from .i18n import t
from .models import Order, OrderLoad, OrderMessage, Truck, TruckDayOff, YardStock, hash_claim_token
from .serializers import (
    CustomerOrderSerializer,
    DayOffSerializer,
    EstimateSerializer,
    InvoiceSerializer,
    LoadAssignmentSerializer,
    MessageSerializer,
    OrderSerializer,
    OrderSummarySerializer,
    StaffOrderSerializer,
    StaffOrderSummarySerializer,
    StockUpdateSerializer,
    TruckUpdateSerializer,
    price_order,
)

ACTIVE_STATUSES = [Order.Status.NEW, Order.Status.CONTACTED, Order.Status.SCHEDULED]


def _unread(from_staff: bool) -> Count:
    """Count unread messages written by the given side."""
    return Count(
        "messages",
        filter=Q(messages__from_staff=from_staff, messages__read_at__isnull=True),
        distinct=True,
    )


def _mark_read(order: Order, from_staff: bool) -> None:
    order.messages.filter(from_staff=from_staff, read_at__isnull=True).update(read_at=timezone.now())


def _require_messaging() -> None:
    """Messaging can be switched off (INTAKE_MESSAGING_ENABLED); see README."""
    if not settings.INTAKE_MESSAGING_ENABLED:
        raise NotFound(t("validation__messaging--disabled"))


def _updates(order: Order, query_params, viewer_is_staff: bool) -> dict:
    """New messages since ``?after=<message id>`` plus the order's last change.

    Open order pages poll this so replies show up without a reload. When
    ``updated_at`` moves (status, date, invoice...) the page refetches.
    """
    try:
        after = int(query_params.get("after") or 0)
    except ValueError:
        after = 0
    messages = list(order.messages.filter(id__gt=after).select_related("author", "order"))
    # The viewer is looking at the thread, so the other side's messages are read.
    _mark_read(order, from_staff=not viewer_is_staff)
    return {"messages": MessageSerializer(messages, many=True).data, "updated_at": order.updated_at}


def _customer_plan(result: dispatch.Plan) -> dict:
    """What the public form learns from routing: coverage, problems, next date."""
    data = dispatch.localize(result.as_dict())
    for load in data["loads"]:
        # Trucks are our business; the customer only sees where it ships from.
        load.pop("truck", None)
        load.pop("truck_name", None)
    return data


# --- Public --------------------------------------------------------------------


class PublicAPIView(APIView):
    # No authentication: a stale JWT left in the browser can't 401 these.
    authentication_classes: list = []
    permission_classes = [AllowAny]


class CatalogView(PublicAPIView):
    def get(self, request):
        return Response(pricing.catalog())


class EstimateView(PublicAPIView):
    """Live quote for the order form: coverage for the zip, routing, price."""

    throttle_scope = "intake_estimate"

    def post(self, request):
        serializer = EstimateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        quantities = pricing.normalize_quantities(data["items"])
        quote, result = price_order(quantities, data["zip_code"], data.get("preferred_date"))
        return Response({"quote": quote or None, "plan": _customer_plan(result)})


class OrderCreateView(APIView):
    """Order or contact form. Signed-in customers get it filed to their account."""

    authentication_classes = [OptionalJWTAuthentication]
    permission_classes = [AllowAny]
    throttle_scope = "intake_submit"

    def post(self, request):
        user = request.user if request.user.is_authenticated else None
        if user is None:
            check_human(request)

        serializer = OrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        claim_token = None
        plan_data = None
        with transaction.atomic():
            order = serializer.save(customer=user)
            if user is None:
                claim_token = order.issue_claim_token()
                order.save(update_fields=["claim_token_hash"])
            if order.request_type == Order.RequestType.DELIVERY:
                # Booking the loads holds the trucks' time for the next quote.
                plan_data = dispatch.assign(order).as_dict()
            transaction.on_commit(lambda: notifications.notify_new_order(order, claim_token))

        return Response(
            {
                "id": order.id,
                "request_type": order.request_type,
                "quote": pricing.localize_quote(order.quote),
                "preferred_date": order.preferred_date,
                "plan_status": plan_data["status"] if plan_data else None,
                # Lets a guest attach this order to an account right away.
                "claim_token": claim_token,
            },
            status=status.HTTP_201_CREATED,
        )


# --- Customer ------------------------------------------------------------------


class MyOrdersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSummarySerializer
    pagination_class = None

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user).annotate(unread_count=_unread(from_staff=True))


class MyOrderDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerOrderSerializer

    def get_queryset(self):
        return Order.objects.filter(customer=self.request.user).prefetch_related("messages__author")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _mark_read(instance, from_staff=True)
        return Response(self.get_serializer(instance).data)


class MyOrderMessageView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "intake_message"

    def post(self, request, pk):
        _require_messaging()
        order = get_object_or_404(Order, pk=pk, customer=request.user)
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(order=order, author=request.user, from_staff=False)
        transaction.on_commit(lambda: notifications.notify_customer_message(message))
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class MyOrderUpdatesView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "account_poll"

    def get(self, request, pk):
        _require_messaging()
        order = get_object_or_404(Order, pk=pk, customer=request.user)
        return Response(_updates(order, request.query_params, viewer_is_staff=False))


class ClaimOrderView(APIView):
    """Attach a guest order to the signed-in account using its emailed token."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "intake_claim"

    def post(self, request):
        token = str(request.data.get("token") or "")
        order = Order.objects.filter(claim_token_hash=hash_claim_token(token)).first() if token else None
        if order is None:
            return Response({"detail": t("validation__claim--invalid")}, status=status.HTTP_404_NOT_FOUND)
        order.customer = request.user
        order.claim_token_hash = ""
        order.save(update_fields=["customer", "claim_token_hash"])
        return Response({"id": order.id})


# --- Staff ---------------------------------------------------------------------


class StaffSummaryView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        now = timezone.now()
        today = timezone.localdate()
        counts = dict(Order.objects.values_list("status").annotate(n=Count("id")).order_by())
        active = Order.objects.filter(status__in=ACTIVE_STATUSES)
        upcoming = (
            Order.objects.filter(
                status=Order.Status.SCHEDULED,
                scheduled_date__gte=today,
                scheduled_date__lte=today + timedelta(days=14),
            )
            .order_by("scheduled_date", "delivery_window")[:10]
        )
        return Response(
            {
                "status_counts": {s: counts.get(s, 0) for s in Order.Status.values},
                "messaging_enabled": settings.INTAKE_MESSAGING_ENABLED,
                "unread_messages": OrderMessage.objects.filter(from_staff=False, read_at__isnull=True).count(),
                "new_this_week": Order.objects.filter(created_at__gte=now - timedelta(days=7)).count(),
                "rush_open": active.filter(is_rush=True).exclude(status=Order.Status.SCHEDULED).count(),
                "needs_dispatch": active.filter(
                    request_type=Order.RequestType.DELIVERY,
                    plan_status__in=[Order.PlanStatus.NO_CAPACITY, Order.PlanStatus.OUT_OF_STOCK],
                ).count(),
                "loads_today": OrderLoad.objects.filter(date=today, order__status__in=ACTIVE_STATUSES).count(),
                "upcoming": StaffOrderSummarySerializer(upcoming, many=True).data,
            }
        )


class StaffOrderListView(generics.ListAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = StaffOrderSummarySerializer

    def get_queryset(self):
        params = self.request.query_params
        qs = Order.objects.annotate(unread_count=_unread(from_staff=False))
        if status_filter := params.get("status"):
            qs = qs.filter(status__in=status_filter.split(","))
        if request_type := params.get("request_type"):
            qs = qs.filter(request_type=request_type)
        if params.get("rush") == "1":
            qs = qs.filter(is_rush=True)
        if params.get("needs_dispatch") == "1":
            qs = qs.filter(plan_status__in=[Order.PlanStatus.NO_CAPACITY, Order.PlanStatus.OUT_OF_STOCK])
        if params.get("unread") == "1":
            qs = qs.filter(unread_count__gt=0)
        if search := params.get("q", "").strip():
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(zip_code__startswith=search)
                | Q(delivery_address__icontains=search)
            )
        ordering = {
            "newest": ["-created_at"],
            "oldest": ["created_at"],
            "preferred": ["preferred_date", "created_at"],
            "scheduled": ["scheduled_date", "delivery_window", "created_at"],
        }.get(params.get("ordering", "newest"), ["-created_at"])
        return qs.order_by(*ordering)


class StaffOrderDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminUser]
    serializer_class = StaffOrderSerializer
    http_method_names = ["get", "patch"]
    queryset = Order.objects.select_related("customer").prefetch_related(
        "messages__author", "loads__yard", "loads__truck"
    )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        _mark_read(instance, from_staff=False)
        return Response(self.get_serializer(instance).data)

    def perform_update(self, serializer):
        before = (serializer.instance.status, serializer.instance.scheduled_date, serializer.instance.delivery_window)
        date_before = serializer.instance.delivery_date
        notify = serializer.validated_data.get("notify_customer", False)
        instance = serializer.save()
        if instance.delivery_date != date_before:
            dispatch.move_to_date(instance)
        if notify and (instance.status, instance.scheduled_date, instance.delivery_window) != before:
            transaction.on_commit(lambda: notifications.notify_status_change(instance))


class StaffReplanView(APIView):
    """Route an order again from scratch (replacing hand-assigned trucks)."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        if order.request_type != Order.RequestType.DELIVERY or not order.items:
            raise ValidationError({"detail": t("validation__dispatch--nothing-to-plan")})
        dispatch.assign(order)
        return Response(StaffOrderSerializer(Order.objects.get(pk=pk)).data)


class StaffLoadView(APIView):
    """Move one load to another truck (or unassign it)."""

    permission_classes = [IsAdminUser]

    def patch(self, request, pk, load_id):
        load = get_object_or_404(OrderLoad.objects.select_related("order"), pk=load_id, order_id=pk)
        serializer = LoadAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            dispatch.reassign_load(load, serializer.validated_data["truck"])
        except ValueError as exc:
            raise ValidationError({"truck": t("validation__dispatch--yard-not-listed", yard=str(exc))}) from exc
        return Response(StaffOrderSerializer(Order.objects.get(pk=pk)).data)


class StaffOrderMessageView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        _require_messaging()
        order = get_object_or_404(Order, pk=pk)
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(order=order, author=request.user, from_staff=True)
        transaction.on_commit(lambda: notifications.notify_staff_reply(message))
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class StaffOrderUpdatesView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        _require_messaging()
        order = get_object_or_404(Order, pk=pk)
        return Response(_updates(order, request.query_params, viewer_is_staff=True))


class StaffInvoiceView(APIView):
    """The verified invoice for an order.

    GET returns the saved invoice, or a draft built from the order and its
    loads (``exists: false``). PUT saves the whole invoice; DELETE discards it.
    """

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        invoice = invoicing.get_invoice(order)
        if invoice is None:
            return Response(invoicing.draft_payload(order))
        return Response(invoicing.invoice_payload(invoice))

    def put(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        serializer = InvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice, just_published = invoicing.save(order, serializer.validated_data)
        if just_published and serializer.validated_data["notify_customer"]:
            transaction.on_commit(lambda: notifications.notify_invoice(order))
        return Response(invoicing.invoice_payload(invoice))

    def delete(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        invoicing.delete(order)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffInvoicePreviewView(APIView):
    """Price an invoice as it's being edited, without saving it."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        get_object_or_404(Order, pk=pk)
        serializer = InvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(invoicing.preview(serializer.validated_data))


# --- Dispatch board --------------------------------------------------------------


class DispatchBoardView(APIView):
    """One day's trucks, loads and yard stock: ``?date=YYYY-MM-DD`` (default today)."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        raw = request.query_params.get("date")
        try:
            day = date.fromisoformat(raw) if raw else timezone.localdate()
        except ValueError as exc:
            raise ValidationError({"date": t("validation__date--invalid")}) from exc
        return Response(dispatch.day_board(day))


class StockUpdateView(generics.UpdateAPIView):
    """Flip a product in or out of stock at a yard."""

    permission_classes = [IsAdminUser]
    serializer_class = StockUpdateSerializer
    queryset = YardStock.objects.all()
    http_method_names = ["patch"]


class TruckUpdateView(generics.UpdateAPIView):
    """Take a truck out of service (or back in)."""

    permission_classes = [IsAdminUser]
    serializer_class = TruckUpdateSerializer
    queryset = Truck.objects.all()
    http_method_names = ["patch"]


class TruckDayOffView(APIView):
    """POST {date, reason} marks a truck off for a day; DELETE ?date= clears it."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        truck = get_object_or_404(Truck, pk=pk)
        serializer = DayOffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        TruckDayOff.objects.update_or_create(
            truck=truck,
            date=serializer.validated_data["date"],
            defaults={"reason": serializer.validated_data.get("reason", "")},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, pk):
        truck = get_object_or_404(Truck, pk=pk)
        try:
            day = date.fromisoformat(request.query_params.get("date", ""))
        except ValueError as exc:
            raise ValidationError({"date": t("validation__date--invalid")}) from exc
        TruckDayOff.objects.filter(truck=truck, date=day).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
