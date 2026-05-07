"""DriverProfile — extended profile for users with role = 'driver'.

M1 scope: schema + approval/territory queryset manager.
Application / approval / reject endpoints land in M3.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from .managers import DriverProfileManager


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AvailableHours(models.TextChoices):
    MORNING = "morning", "Morning (8am–12pm)"
    AFTERNOON = "afternoon", "Afternoon (12pm–5pm)"
    EVENING = "evening", "Evening (5pm–8pm)"
    FLEXIBLE = "flexible", "Flexible"


class BackgroundCheckStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CLEARED = "cleared", "Cleared"
    FAILED = "failed", "Failed"


class DriverProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="driver_profile",
        limit_choices_to={"role": "driver"},
    )

    # ── Vehicle ─────────────────────────────────
    vehicle_make = models.CharField(max_length=50)
    vehicle_model = models.CharField(max_length=50)
    vehicle_year = models.IntegerField()
    license_plate = models.CharField(max_length=20)

    # ── Availability ────────────────────────────
    available_days = models.JSONField(
        default=list,
        help_text='Array of day names: ["monday", "tuesday", ...]',
    )
    available_hours = models.CharField(
        max_length=20, choices=AvailableHours.choices, default=AvailableHours.FLEXIBLE,
    )

    # ── Approval workflow ───────────────────────
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
        db_index=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="drivers_approved",
        limit_choices_to={"role": "admin"},
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")

    # ── Phase 1.5 additions ─────────────────────
    territory = models.ForeignKey(
        "territories.Territory",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="drivers",
    )
    rating = models.DecimalField(
        max_digits=3, decimal_places=2, null=True, blank=True,
    )
    acceptance_rate = models.DecimalField(
        max_digits=4, decimal_places=3, null=True, blank=True,
    )
    total_earnings = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
    )
    background_check_status = models.CharField(
        max_length=20,
        choices=BackgroundCheckStatus.choices,
        default=BackgroundCheckStatus.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DriverProfileManager()

    class Meta:
        db_table = "drivers_driverprofile"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.full_name} — {self.approval_status}"

    @property
    def is_approved(self):
        return self.approval_status == ApprovalStatus.APPROVED
