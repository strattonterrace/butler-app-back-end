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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "territories_territory"
        ordering = ["name"]
        verbose_name_plural = "Territories"

    def __str__(self):
        return self.name
