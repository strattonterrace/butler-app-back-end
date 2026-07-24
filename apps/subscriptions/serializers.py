"""Subscription serializers — read shapes for the billing UI."""
from rest_framework import serializers

from .models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    """Full billing state for the client Settings page. Stripe IDs stay
    server-side — the frontend never needs them."""

    class Meta:
        model = Subscription
        fields = (
            "status",
            "plan_amount",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "cancelled_at",
            "created_at",
        )
        read_only_fields = fields
