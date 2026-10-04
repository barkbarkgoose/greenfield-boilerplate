"""Intake app URL configuration."""

from django.urls import path

from . import views

public_urlpatterns = [
    path("catalog/", views.CatalogView.as_view(), name="intake-catalog"),
    path("estimate/", views.EstimateView.as_view(), name="intake-estimate"),
    path("orders/", views.OrderCreateView.as_view(), name="intake-order-create"),
]

account_urlpatterns = [
    path("orders/", views.MyOrdersView.as_view(), name="account-orders"),
    path("orders/<int:pk>/", views.MyOrderDetailView.as_view(), name="account-order"),
    path("orders/<int:pk>/messages/", views.MyOrderMessageView.as_view(), name="account-order-messages"),
    path("orders/<int:pk>/updates/", views.MyOrderUpdatesView.as_view(), name="account-order-updates"),
    path("claim/", views.ClaimOrderView.as_view(), name="account-claim"),
]

staff_urlpatterns = [
    path("summary/", views.StaffSummaryView.as_view(), name="staff-summary"),
    path("orders/", views.StaffOrderListView.as_view(), name="staff-orders"),
    path("orders/<int:pk>/", views.StaffOrderDetailView.as_view(), name="staff-order"),
    path("orders/<int:pk>/replan/", views.StaffReplanView.as_view(), name="staff-order-replan"),
    path("orders/<int:pk>/loads/<int:load_id>/", views.StaffLoadView.as_view(), name="staff-order-load"),
    path("orders/<int:pk>/messages/", views.StaffOrderMessageView.as_view(), name="staff-order-messages"),
    path("orders/<int:pk>/updates/", views.StaffOrderUpdatesView.as_view(), name="staff-order-updates"),
    path("orders/<int:pk>/invoice/", views.StaffInvoiceView.as_view(), name="staff-order-invoice"),
    path(
        "orders/<int:pk>/invoice/preview/",
        views.StaffInvoicePreviewView.as_view(),
        name="staff-order-invoice-preview",
    ),
    path("dispatch/", views.DispatchBoardView.as_view(), name="staff-dispatch"),
    path("stock/<int:pk>/", views.StockUpdateView.as_view(), name="staff-stock"),
    path("trucks/<int:pk>/", views.TruckUpdateView.as_view(), name="staff-truck"),
    path("trucks/<int:pk>/days-off/", views.TruckDayOffView.as_view(), name="staff-truck-days-off"),
]
