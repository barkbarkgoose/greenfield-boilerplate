"""URL configuration for config project."""

from django.contrib import admin
from django.urls import include, path

from apps.intake import urls as intake_urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/intake/", include(intake_urls.public_urlpatterns)),
    path("api/v1/garage/", include(intake_urls.garage_urlpatterns)),
    path("api/v1/manage/", include(intake_urls.staff_urlpatterns)),
]
