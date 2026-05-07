from django.contrib import admin

from .models import DriverProfile


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user", "approval_status", "vehicle_make", "vehicle_model",
        "vehicle_year", "background_check_status", "rating", "created_at",
    )
    list_filter = ("approval_status", "background_check_status", "available_hours")
    search_fields = ("user__email", "user__full_name", "license_plate")
    readonly_fields = ("id", "approved_at", "rejected_at", "created_at", "updated_at")
