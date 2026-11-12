"""URL configuration for config project."""

from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import include, path, reverse


def health(request):
    """Liveness for uptime checks: the app answers and the DB connects.

    Deliberately anonymous and minimal.
    """

    try:
        connection.ensure_connection()
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "db_unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def admin_login(request):
    """The admin has no password form: staff sign in to the app with a passkey, which
    also opens an admin session, and are sent back here."""

    next_url = request.GET.get("next", "")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = reverse("admin:index")
    return redirect(f"/login?{urlencode({'redirect': next_url})}")


admin.site.login = admin_login

urlpatterns = [
    path("health/", health, name="health"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
]
