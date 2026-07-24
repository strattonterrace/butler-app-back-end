"""Driver application + approval services (BACKEND_SCOPE §11).

Views stay thin; the role flip, approval side effects, and notifications
live here. Approval/rejection are the gatekeepers for the whole gig layer —
an unapproved driver can't be assigned (see services in apps.requests and
the IsApprovedDriver permission), so these transitions matter.
"""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.activity.services import ActivityType, emit
from apps.notifications import services as notifications

from .models import ApprovalStatus, DriverProfile

logger = logging.getLogger("butler.drivers")


# ─────────────────────────────────────────────
# Apply
# ─────────────────────────────────────────────
@transaction.atomic
def apply_as_driver(
    *,
    user,
    vehicle_make,
    vehicle_model,
    vehicle_year,
    license_plate,
    available_days,
    available_hours="flexible",
    phone="",
) -> DriverProfile:
    """Convert an authenticated user into a pending driver (§11 apply).

    Flips role → driver and creates the DriverProfile. Rejected if the user
    already holds a driver profile. Admins are notified so an application
    never sits unseen.
    """
    if user.role == Role.DRIVER or getattr(user, "driver_profile", None) is not None:
        # String message so Django keeps `code` (dict messages drop it).
        raise ValidationError(
            "You already have a driver application on file.",
            code="DRV_ALREADY_APPLIED",
        )

    update_fields = ["role"]
    user.role = Role.DRIVER
    if phone:
        user.phone = phone
        update_fields.append("phone")
    user.save(update_fields=update_fields)

    profile = DriverProfile.objects.create(
        user=user,
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_year=int(vehicle_year),
        license_plate=license_plate,
        available_days=available_days,
        available_hours=available_hours,
        approval_status=ApprovalStatus.PENDING,
    )
    emit(
        ActivityType.DRIVER_APPLICATION,
        message=f"{user.full_name} applied to drive",
        actor=user,
    )
    transaction.on_commit(lambda: notifications.send_driver_application_email(profile))
    logger.info("driver application submitted: %s", user.email)
    return profile


# ─────────────────────────────────────────────
# Approve / Reject
# ─────────────────────────────────────────────
@transaction.atomic
def approve_driver(*, profile, by_admin) -> DriverProfile:
    """Approve a pending application. Idempotent-safe: re-approving an
    already-approved driver is a no-op error rather than a double email."""
    if profile.approval_status == ApprovalStatus.APPROVED:
        raise ValidationError(
            "This driver is already approved.",
            code="DRV_ALREADY_APPROVED",
        )

    profile.approval_status = ApprovalStatus.APPROVED
    profile.approved_by = by_admin
    profile.approved_at = timezone.now()
    profile.rejected_at = None
    profile.rejection_reason = ""
    profile.save(update_fields=[
        "approval_status", "approved_by", "approved_at",
        "rejected_at", "rejection_reason", "updated_at",
    ])
    emit(
        ActivityType.DRIVER_APPROVED,
        message=f"{profile.user.full_name} was approved to drive",
        actor=by_admin,
    )
    transaction.on_commit(lambda: notifications.send_driver_approved_email(profile))
    logger.info("driver approved: target=%s by=%s", profile.user.email, by_admin.email)
    return profile


@transaction.atomic
def reject_driver(*, profile, by_admin, reason="") -> DriverProfile:
    """Reject an application with a reason. A previously-approved driver can
    be rejected (revoked) — that also drops them out of assignment eligibility."""
    profile.approval_status = ApprovalStatus.REJECTED
    profile.rejection_reason = reason or ""
    profile.rejected_at = timezone.now()
    profile.save(update_fields=[
        "approval_status", "rejection_reason", "rejected_at", "updated_at",
    ])
    emit(
        ActivityType.DRIVER_REJECTED,
        message=f"{profile.user.full_name}'s driver application was declined",
        actor=by_admin,
        reason=reason,
    )
    transaction.on_commit(lambda: notifications.send_driver_rejected_email(profile))
    logger.info("driver rejected: target=%s by=%s", profile.user.email, by_admin.email)
    return profile


# ─────────────────────────────────────────────
# Listing helpers
# ─────────────────────────────────────────────
_ACTIVE_TASK_STATUSES = ["assigned", "in_progress"]


def available_drivers_for(user):
    """Approved drivers an operator/admin can assign, annotated with their
    live workload and ordered least-busy-first (§11 available).

    Operators are scoped to their own territory; admins see every approved
    driver. `current_task_count` counts only in-flight assignments so the
    dropdown surfaces who's free right now.
    """
    qs = DriverProfile.objects.approved().select_related("user", "territory")

    if user.role == Role.OPERATOR:
        if user.territory_id is None:
            return DriverProfile.objects.none()
        qs = qs.filter(territory_id=user.territory_id)

    return qs.annotate(
        current_task_count=Count(
            "user__requests_assigned",
            filter=Q(user__requests_assigned__status__in=_ACTIVE_TASK_STATUSES),
            distinct=True,
        ),
    ).order_by("current_task_count", "user__full_name")


def pending_applications():
    """All pending driver applications, oldest first (§11 pending)."""
    return (
        DriverProfile.objects.pending()
        .select_related("user", "territory")
        .order_by("created_at")
    )
