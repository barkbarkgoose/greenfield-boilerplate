"""Intake app URL configuration."""

from django.urls import path

from .views import CatalogView, EstimateView, ServiceRequestCreateView

urlpatterns = [
    path("catalog/", CatalogView.as_view(), name="intake-catalog"),
    path("estimate/", EstimateView.as_view(), name="intake-estimate"),
    path("requests/", ServiceRequestCreateView.as_view(), name="intake-request-create"),
]
