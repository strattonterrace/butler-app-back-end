"""ServiceRequest visibility manager.

This file is the **canonical source** for who can see which requests.
Every M3 list endpoint should call `ServiceRequest.objects.visible_to(user)`
rather than reinventing the rule per view.

Visibility matrix (mirrors BACKEND_SCOPE §10):

  Role       | What they see
  -----------|----------------------------------------------------------------
  admin      | All requests, all territories
  operator   | Requests whose client lives in the operator's territory
             | (a request "belongs" to a territory through its client)
  driver     | Requests assigned to them (driver=user)
  client     | Requests they submitted (client=user)
  anonymous  | Nothing

Cross-role leakage is prevented because filters are AND'd onto the queryset.
Defensive choice: when a territory is missing on either side, deny.
"""
from django.db import models


class ServiceRequestQuerySet(models.QuerySet):
    # ── Status filters ─────────────────────────
    def submitted(self):
        return self.filter(status="submitted")

    def reviewed(self):
        return self.filter(status="reviewed")

    def assigned(self):
        return self.filter(status="assigned")

    def in_progress(self):
        return self.filter(status="in_progress")

    def completed(self):
        return self.filter(status="completed")

    def open(self):
        """Anything still in flight — submitted through in_progress."""
        return self.filter(status__in=["submitted", "reviewed", "assigned", "in_progress"])

    # ── Visibility ─────────────────────────────
    def visible_to(self, user):
        """Filter to the requests this user is permitted to see.

        Pure function on the queryset — never mutates anything, always returns
        a new queryset. Composes cleanly: ``ServiceRequest.objects.open().visible_to(user)``.
        """
        if user is None or not user.is_authenticated:
            return self.none()

        role = user.role

        if role == "admin":
            return self

        if role == "client":
            return self.filter(client=user)

        if role == "driver":
            return self.filter(driver=user)

        if role == "operator":
            # An operator sees requests whose client lives in their territory.
            # Fail closed if the operator has no territory.
            if user.territory_id is None:
                return self.none()
            return self.filter(client__territory_id=user.territory_id)

        # Unknown role → deny
        return self.none()

    def available_for_driver(self, driver):
        """Unassigned, operator-reviewed requests that an approved driver
        in the same territory can pick up.

        Architecture note: a request reaches `reviewed` only after an operator
        validates it. Drivers never see `submitted` requests directly — that
        prevents partial / unscreened tasks from leaking to the gig layer.
        """
        if driver is None or driver.role != "driver":
            return self.none()

        profile = getattr(driver, "driver_profile", None)
        if profile is None or profile.approval_status != "approved":
            return self.none()
        if profile.territory_id is None:
            return self.none()

        return self.filter(
            status="reviewed",
            driver__isnull=True,
            client__territory_id=profile.territory_id,
        )


ServiceRequestManager = models.Manager.from_queryset(ServiceRequestQuerySet)
