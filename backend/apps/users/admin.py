"""Users app admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Passkey, User


class PasskeyInline(admin.TabularInline):
    """Saved passkeys. Delete one here if a device is lost (or use reset_passkeys)."""

    model = Passkey
    extra = 0
    fields = ["name", "created_at", "last_used_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False  # passkeys are created from the site's sign-in flow


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["id", "email", "name", "is_staff", "passkey_required", "is_active", "created_at"]
    list_filter = ["is_active", "is_staff", "passkey_required"]
    search_fields = ["email", "name"]
    ordering = ["-created_at"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("name",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
        ("Sign-in security", {"fields": ("passkey_required",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "password1", "password2"),
            },
        ),
    )
    inlines = [PasskeyInline]
