"""Users app URL configuration."""

from django.urls import path

from apps.users.views import (
    AuthConfigView,
    LoginView,
    RefreshTokenView,
    RegisterView,
    UserSettingsView,
)

urlpatterns = [
    path("config/", AuthConfigView.as_view(), name="auth-config"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshTokenView.as_view(), name="refresh"),
    path("settings/", UserSettingsView.as_view(), name="user-settings"),
]
