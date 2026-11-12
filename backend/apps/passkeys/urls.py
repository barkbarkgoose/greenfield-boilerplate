"""Passkey URLs, mounted at /api/v1/auth/passkeys/."""

from django.urls import path

from .views import (
    PasskeyDetailView,
    PasskeyListView,
    RegisterBeginView,
    RegisterFinishView,
    SignInBeginView,
    SignInFinishView,
)

urlpatterns = [
    path("", PasskeyListView.as_view(), name="passkey-list"),
    path("<int:pk>/", PasskeyDetailView.as_view(), name="passkey-detail"),
    path("register/begin/", RegisterBeginView.as_view(), name="passkey-register-begin"),
    path("register/finish/", RegisterFinishView.as_view(), name="passkey-register-finish"),
    # nginx rate-limits sign-in like the password login (hosting/provision.sh AUTH_LOCATION)
    path("login/begin/", SignInBeginView.as_view(), name="passkey-login-begin"),
    path("login/finish/", SignInFinishView.as_view(), name="passkey-login-finish"),
]
