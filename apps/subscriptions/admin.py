from django.contrib import admin

from .models import Subscription


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
