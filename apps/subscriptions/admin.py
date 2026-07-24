from django.contrib import admin

from .models import Subscription, WebhookEvent


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user", "status", "plan_amount", "current_period_end",
        "cancel_at_period_end", "updated_at",
    )
    list_filter = ("status", "cancel_at_period_end")
    search_fields = ("user__email", "stripe_customer_id", "stripe_subscription_id")
    readonly_fields = (
        "id", "stripe_customer_id", "stripe_subscription_id",
        "created_at", "updated_at",
    )


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    """Read-only ledger — rows are only ever written by the webhook view."""
    list_display = ("event_type", "stripe_event_id", "created_at")
    list_filter = ("event_type",)
    search_fields = ("stripe_event_id",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
