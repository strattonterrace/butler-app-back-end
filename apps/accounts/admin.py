"""Django admin registration — emergency data access only.

Production user management happens via the API (admin endpoints), not here.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import SavedAddress, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "full_name", "role", "status", "is_staff", "created_at")
    list_filter = ("role", "status", "is_staff", "is_superuser")
    search_fields = ("email", "full_name", "phone")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "last_login")

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "avatar_url")}),
        ("Role & status", {"fields": ("role", "status", "territory")}),
        ("Permissions", {
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
        }),
        ("Timestamps", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "password1", "password2"),
        }),
    )


@admin.register(SavedAddress)
class SavedAddressAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "address", "is_default", "created_at")
    list_filter = ("is_default",)
    search_fields = ("user__email", "label", "address")
    readonly_fields = ("id", "created_at", "updated_at")
