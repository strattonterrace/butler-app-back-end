"""DriverProfile queryset — territory + approval scoping.

Used by:
  - operator's "available drivers for assignment" dropdown (M3)
  - admin pending applications view (M3)
  - the IsApprovedDriver permission gate (M1+)
"""
from django.db import models


class DriverProfileQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(approval_status="approved")

    def pending(self):
        return self.filter(approval_status="pending")

    def rejected(self):
        return self.filter(approval_status="rejected")

    def in_territory(self, territory):
        if territory is None:
            return self.none()
        territory_id = getattr(territory, "id", territory)
        return self.filter(territory_id=territory_id)

    def approved_in_territory(self, territory):
        return self.approved().in_territory(territory)

    def for_operator(self, operator):
        """Drivers an operator can see — approved drivers in their territory."""
        if operator is None or operator.territory_id is None:
            return self.none()
        return self.approved_in_territory(operator.territory_id)


DriverProfileManager = models.Manager.from_queryset(DriverProfileQuerySet)
