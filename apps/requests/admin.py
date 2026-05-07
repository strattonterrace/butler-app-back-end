from django.contrib import admin

from .models import ServiceRequest, StatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "notes", "created_at")
    can_delete = False


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = (
        "title", "client", "driver", "service_type", "urgency",
        "status", "created_at",
    )
    list_filter = ("status", "service_type", "urgency")
    search_fields = ("title", "description", "client__email", "driver__email")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [StatusHistoryInline]


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("request", "from_status", "to_status", "changed_by", "created_at")
    list_filter = ("to_status",)
    search_fields = ("request__title",)
    readonly_fields = ("id", "created_at")
