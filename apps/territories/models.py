"""Territory — geographic franchise unit (Orange County, LA, etc.)."""
import uuid

from django.conf import settings
from django.db import models


class TerritoryStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class Territory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100, unique=True)

    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operated_territory",
        limit_choices_to={"role": "operator"},
    )

    commission_rate = models.DecimalField(
        max_digits=4, decimal_places=2, default=0.20,
        help_text="Operator's cut of territory revenue, e.g. 0.20 = 20%",
    )

    status = models.CharField(
        max_length=20, choices=TerritoryStatus.choices, default=TerritoryStatus.ACTIVE,
        db_index=True,
    )

    # Served ZIP codes — the onboarding location gate matches against these.
    # A new city goes live by adding a Territory row with its ZIPs; no code change.
    zip_codes = models.JSONField(
        default=list, blank=True,
        help_text="List of served ZIP codes, e.g. ['92618', '92660'].",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "territories_territory"
        ordering = ["name"]
        verbose_name_plural = "Territories"

    def __str__(self):
        return self.name

    def serves_zip(self, zip_code: str) -> bool:
        return str(zip_code).strip() in {str(z).strip() for z in (self.zip_codes or [])}


class WaitlistEntry(models.Model):
    """Someone who wanted Butler but isn't in a served area yet.

    Every out-of-area signup lands here — this doubles as the demand map that
    tells Butler where to expand next.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    zip_code = models.CharField(max_length=12, blank=True, default="")
    full_name = models.CharField(max_length=150, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "territories_waitlistentry"
        ordering = ["-created_at"]
        verbose_name_plural = "Waitlist entries"
        constraints = [
            models.UniqueConstraint(
                fields=["email", "zip_code"], name="unique_waitlist_email_zip",
            ),
        ]

    def __str__(self):
        return f"{self.email} ({self.zip_code or 'no zip'})"
