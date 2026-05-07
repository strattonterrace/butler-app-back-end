from django.contrib import admin

from .models import Territory


@admin.register(Territory)
class TerritoryAdmin(admin.ModelAdmin):
    list_display = ("name", "operator", "commission_rate", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")
