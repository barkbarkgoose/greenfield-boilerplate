"""Users app URL configuration."""

from django.urls import path

from apps.users.views import (
    LoginView,
    PasskeyDetailView,
    PasskeyListView,
    PasskeyLoginView,
    PasskeyRegisterOptionsView,
    PasskeyRegisterView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RefreshTokenView,
    RegisterView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshTokenView.as_view(), name="refresh"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path("passkeys/", PasskeyListView.as_view(), name="passkeys"),
    path("passkeys/login/", PasskeyLoginView.as_view(), name="passkey-login"),
    path(
        "passkeys/register/options/",
        PasskeyRegisterOptionsView.as_view(),
        name="passkey-register-options",
    ),
    path("passkeys/register/", PasskeyRegisterView.as_view(), name="passkey-register"),
    path("passkeys/<int:pk>/", PasskeyDetailView.as_view(), name="passkey-detail"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]
