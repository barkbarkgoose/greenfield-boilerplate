"""URL configuration for config project."""

from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    """Liveness for uptime checks: the app answers and the DB connects.

    Deliberately anonymous and minimal.
    """

    try:
        connection.ensure_connection()
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "db_unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
]
