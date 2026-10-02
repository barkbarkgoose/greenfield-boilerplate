"""Intake app URL configuration."""

from django.urls import path

from . import views

public_urlpatterns = [
    path("catalog/", views.CatalogView.as_view(), name="intake-catalog"),
    path("estimate/", views.EstimateView.as_view(), name="intake-estimate"),
    path("requests/", views.ServiceRequestCreateView.as_view(), name="intake-request-create"),
]

garage_urlpatterns = [
    path("vehicles/", views.MyVehiclesView.as_view(), name="garage-vehicles"),
    path("vehicles/<int:pk>/", views.MyVehicleDetailView.as_view(), name="garage-vehicle"),
    path("requests/", views.MyRequestsView.as_view(), name="garage-requests"),
    path("requests/<int:pk>/", views.MyRequestDetailView.as_view(), name="garage-request"),
    path(
        "requests/<int:pk>/messages/",
        views.MyRequestMessageView.as_view(),
        name="garage-request-messages",
    ),
    path("claim/", views.ClaimRequestView.as_view(), name="garage-claim"),
]

staff_urlpatterns = [
    path("summary/", views.StaffSummaryView.as_view(), name="staff-summary"),
    path("requests/", views.StaffRequestListView.as_view(), name="staff-requests"),
    path("requests/<int:pk>/", views.StaffRequestDetailView.as_view(), name="staff-request"),
    path(
        "requests/<int:pk>/messages/",
        views.StaffRequestMessageView.as_view(),
        name="staff-request-messages",
    ),
]
