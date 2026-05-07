from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "type", "message", "actor", "target_request")
    list_filter = ("type", "created_at")
    search_fields = ("message", "actor__email", "actor__full_name")
    readonly_fields = ("id", "created_at", "type", "message", "actor", "target_request", "metadata")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        # Activity is system-generated; never hand-create from admin
        return False

    def has_change_permission(self, request, obj=None):
        return False
