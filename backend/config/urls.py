"""URL configuration for config project."""

import sys

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.intake import urls as intake_urls

if settings.ADMIN_URL_IS_RANDOM:
    # No ADMIN_URL set: say where this process put the admin (see settings).
    print(f"Django admin for this run: /{settings.ADMIN_URL} (set ADMIN_URL to fix it)", file=sys.stderr)

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/auth/", include("apps.users.urls")),
    path("api/v1/intake/", include(intake_urls.public_urlpatterns)),
    path("api/v1/account/", include(intake_urls.account_urlpatterns)),
    path("api/v1/manage/", include(intake_urls.staff_urlpatterns)),
]
