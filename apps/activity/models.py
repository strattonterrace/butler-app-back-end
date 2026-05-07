"""ActivityLog — events powering the admin Live Operations feed.

M1 scope: schema only. The activity-feed endpoint and event-emit hooks land in
M3 (when the request lifecycle and subscription webhooks fire real events).

Event types match the `MOCK_ACTIVITY` shape in src/mock/data.js so the
frontend's AdminDashboard live feed wires straight onto this table.
"""
import uuid

from django.conf import settings
from django.db import models


class ActivityType(models.TextChoices):
    # Request lifecycle events (M3 — fired from status transitions)
    ORDER_SUBMITTED = "order_submitted", "Order Submitted"
    ORDER_ASSIGNED = "order_assigned", "Order Assigned"
    ORDER_PICKUP = "order_pickup", "Order Pickup"
    ORDER_COMPLETED = "order_completed", "Order Completed"
    ORDER_CANCELLED = "order_cancelled", "Order Cancelled"

    # Subscription events (M2 — fired from Stripe webhooks)
    SUBSCRIPTION_NEW = "subscription_new", "New Subscription"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled", "Subscription Cancelled"
    PAYMENT_FAILED = "payment_failed", "Payment Failed"

    # User / driver events
    DRIVER_APPLICATION = "driver_application", "Driver Application"
    DRIVER_APPROVED = "driver_approved", "Driver Approved"
    DRIVER_REJECTED = "driver_rejected", "Driver Rejected"
    RATING = "rating", "Rating Left"
    USER_SUSPENDED = "user_suspended", "User Suspended"


class ActivityLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    type = models.CharField(
        max_length=40, choices=ActivityType.choices, db_index=True,
    )

    # Pre-rendered display string for the feed — matches MOCK_ACTIVITY.message
    # e.g. "Marcus Johnson completed grocery pickup for Jane Smith"
    message = models.CharField(max_length=500)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="activity_emitted",
        help_text="The user whose action triggered this event",
    )

    # Optional FK to a related request (most events relate to a service request)
    target_request = models.ForeignKey(
        "service_requests.ServiceRequest",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="activity_entries",
    )

    # Free-form payload for event-specific data (e.g. rating value, tip amount)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "activity_activitylog"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["type", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.type}] {self.message}"
