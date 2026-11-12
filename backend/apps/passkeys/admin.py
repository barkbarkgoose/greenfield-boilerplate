"""Passkeys admin: see who has which passkeys, and remove one (e.g. a lost device)."""

from django.contrib import admin

from .models import Passkey


@admin.register(Passkey)
class PasskeyAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "rp_id", "backed_up", "created_at", "last_used_at"]
    list_filter = ["backed_up", "rp_id"]
    search_fields = ["user__email", "name"]
    fields = ["user", "name", "rp_id", "backed_up", "created_at", "last_used_at"]
    readonly_fields = fields

    def has_add_permission(self, request):
        return False  # passkeys are created by the user's browser, in the app
