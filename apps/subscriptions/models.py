"""Subscription models — Stripe billing state + webhook idempotency ledger."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past Due"
    CANCELLED = "cancelled", "Cancelled"
    INCOMPLETE = "incomplete", "Incomplete"
    INACTIVE = "inactive", "Inactive"


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription",
    )

    # Stripe references — created on register (customer) / checkout (subscription).
    # Both nullable so the row can exist before Stripe round-trips complete.
    # Postgres treats multiple NULLs as distinct, so the unique constraint holds.
    stripe_customer_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True, db_index=True,
    )
    stripe_subscription_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True, db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.INACTIVE,
        db_index=True,
    )

    plan_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("199.00"),
    )

    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subscriptions_subscription"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} — {self.status}"

    @property
    def is_active(self):
        return self.status == SubscriptionStatus.ACTIVE


class WebhookEvent(models.Model):
    """Idempotency ledger for Stripe webhooks.

    Stripe retries delivery until it sees a 2xx, and the same event can
    arrive twice concurrently. The unique stripe_event_id means an event
    is processed exactly once — the row is inserted in the same
    transaction as the handler's writes, so a failed handler rolls the
    ledger entry back and the retry gets a clean run.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_webhookevent"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} ({self.stripe_event_id})"
