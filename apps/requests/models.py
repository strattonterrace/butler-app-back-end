"""ServiceRequest + StatusHistory.

M1 scope: schema + visibility manager + state machine. The lifecycle
endpoints land in M3 but the rules they'll enforce are codified here so
the view layer can never go off-script.
"""
import uuid

from django.conf import settings
from django.db import models

from .managers import ServiceRequestManager


class ServiceType(models.TextChoices):
    GROCERY = "grocery", "Grocery Pickup"
    PHARMACY = "pharmacy", "Pharmacy Pickup"
    DRY_CLEANING = "dry_cleaning", "Dry Cleaning"
    PACKAGE = "package", "Package Drop-off"
    RETAIL_RETURN = "retail_return", "Retail Return"
    FOOD_PICKUP = "food_pickup", "Food Pickup"


class Urgency(models.TextChoices):
    ASAP = "asap", "ASAP"
    TODAY = "today", "Today"
    SCHEDULED = "scheduled", "Scheduled"


class ScheduledWindow(models.TextChoices):
    MORNING = "morning", "Morning"
    AFTERNOON = "afternoon", "Afternoon"
    EVENING = "evening", "Evening"


class RequestStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    REVIEWED = "reviewed", "Reviewed"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


class ServiceRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Parties ─────────────────────────────────
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="requests_submitted",
        limit_choices_to={"role": "client"},
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requests_reviewed",
        limit_choices_to={"role": "operator"},
    )
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requests_assigned",
        limit_choices_to={"role": "driver"},
    )

    # ── Request body ────────────────────────────
    service_type = models.CharField(max_length=30, choices=ServiceType.choices, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    pickup_location = models.CharField(max_length=500)
    dropoff_location = models.CharField(max_length=500)

    urgency = models.CharField(
        max_length=20, choices=Urgency.choices, default=Urgency.ASAP, db_index=True,
    )
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_window = models.CharField(
        max_length=20, choices=ScheduledWindow.choices, null=True, blank=True,
    )
    special_instructions = models.TextField(blank=True, default="")
    estimated_budget = models.CharField(max_length=100, blank=True, default="")

    # ── Lifecycle ───────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.SUBMITTED,
        db_index=True,
    )
    cancel_reason = models.TextField(blank=True, default="")
    completion_notes = models.TextField(blank=True, default="")

    # Proof-of-completion image (Cloudinary URL — wired in M3)
    proof_image_url = models.URLField(max_length=500, blank=True, default="")

    # ── Reserved for Phase 3 tipping (per March 31 reply) ─
    tip_amount = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
    )
    tip_stripe_payment_id = models.CharField(
        max_length=255, blank=True, default="",
    )

    # ── Timestamps ──────────────────────────────
    assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ServiceRequestManager()

    class Meta:
        db_table = "requests_servicerequest"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["client", "-created_at"]),
            models.Index(fields=["driver", "status"]),
        ]

    def __str__(self):
        return f"{self.title} [{self.status}]"

    # ─────────────────────────────────────────
    # State machine — single source of truth for the request lifecycle.
    #
    # M3 endpoints will call `can_transition_to()` and never set `status`
    # directly. That's how we keep the audit trail honest and prevent
    # anyone bypassing the matrix in BACKEND_SCOPE §10.
    #
    # Format:  (from_status, to_status): {"roles": {...}, "extras": [...]}
    #   roles  — user roles allowed to perform the transition
    #   extras — additional checks the M3 view must verify
    # ─────────────────────────────────────────
    _TRANSITIONS = {
        ("submitted",   "reviewed"):    {"roles": {"operator", "admin"}, "extras": []},
        ("reviewed",    "assigned"):    {"roles": {"operator", "admin"}, "extras": ["driver_id"]},
        ("assigned",    "in_progress"): {"roles": {"driver"},            "extras": ["assigned_driver_only"]},
        ("in_progress", "completed"):   {"roles": {"driver"},            "extras": ["assigned_driver_only"]},
        ("completed",   "closed"):      {"roles": {"admin"},             "extras": []},
        # Cancellations are special — handled by the role+state check below.
    }

    def can_transition_to(self, new_status, by_user):
        """Return (allowed: bool, error_code: str|None).

        error_code is the machine-readable string the M3 view layer surfaces in
        the error envelope (REQ_INVALID_TRANSITION, REQ_NOT_ASSIGNED_DRIVER,
        PERMISSION_DENIED, REQ_ALREADY_CANCELLED, AUTH_REQUIRED).
        """
        if by_user is None or not by_user.is_authenticated:
            return (False, "AUTH_REQUIRED")

        if self.status == new_status:
            return (False, "REQ_INVALID_TRANSITION")

        if self.status == "cancelled":
            return (False, "REQ_ALREADY_CANCELLED")
        if self.status == "closed":
            return (False, "REQ_INVALID_TRANSITION")

        # Cancellation: special-cased — clients can cancel only before assignment.
        if new_status == "cancelled":
            if by_user.role == "client":
                if self.client_id != by_user.id:
                    return (False, "PERMISSION_DENIED")
                if self.status not in {"submitted", "reviewed"}:
                    return (False, "REQ_INVALID_TRANSITION")
                return (True, None)
            if by_user.role in {"operator", "admin"}:
                return (True, None)
            return (False, "PERMISSION_DENIED")

        rule = self._TRANSITIONS.get((self.status, new_status))
        if rule is None:
            return (False, "REQ_INVALID_TRANSITION")

        if by_user.role not in rule["roles"]:
            return (False, "PERMISSION_DENIED")

        if "assigned_driver_only" in rule["extras"]:
            if self.driver_id != by_user.id:
                return (False, "REQ_NOT_ASSIGNED_DRIVER")

        return (True, None)

    @classmethod
    def allowed_next_statuses(cls, from_status, by_role):
        """Listing helper — what transitions could a `by_role` user perform
        from `from_status`? Useful for UI affordances on the frontend."""
        out = []
        for (src, dst), rule in cls._TRANSITIONS.items():
            if src == from_status and by_role in rule["roles"]:
                out.append(dst)
        if from_status in {"submitted", "reviewed"} and by_role == "client":
            out.append("cancelled")
        # Operator/admin can cancel any open state — spec is "any except closed".
        if from_status in {"submitted", "reviewed", "assigned", "in_progress", "completed"} \
                and by_role in {"operator", "admin"}:
            out.append("cancelled")
        return sorted(set(out))


class StatusHistory(models.Model):
    """Immutable audit trail of every status transition on a request."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="status_history",
    )

    from_status = models.CharField(
        max_length=20, choices=RequestStatus.choices, null=True, blank=True,
    )
    to_status = models.CharField(max_length=20, choices=RequestStatus.choices)

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name="status_changes",
    )
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "requests_statushistory"
        ordering = ["created_at"]
        verbose_name_plural = "Status history"

    def __str__(self):
        return f"{self.request_id}: {self.from_status or '∅'} → {self.to_status}"
