"""Request lifecycle services — the business layer for BACKEND_SCOPE §10.

Views stay thin: parse → call these → serialize. Every status change goes
through `transition_request`, which is the ONLY code path allowed to write
`ServiceRequest.status`. That single funnel is what keeps the audit trail
complete and the state machine honest.
"""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.activity.services import ActivityType, emit
from apps.notifications import services as notifications

from .models import RequestStatus, ServiceRequest, StatusHistory

logger = logging.getLogger("butler.requests")


class TransitionError(Exception):
    """A status transition rejected by the state machine.

    `code` is the machine-readable string for the error envelope;
    `http_status` tells the view which status to return (409 for
    sequencing conflicts, 403 for role/ownership violations).
    """

    _MESSAGES = {
        "REQ_INVALID_TRANSITION": "This status change is not allowed from the request's current state.",
        "REQ_ALREADY_CANCELLED": "This request has already been cancelled.",
        "REQ_NOT_ASSIGNED_DRIVER": "Only the assigned driver can perform this action.",
        "PERMISSION_DENIED": "You don't have permission to perform this status change.",
        "AUTH_REQUIRED": "Authentication required.",
    }
    _FORBIDDEN = {"PERMISSION_DENIED", "REQ_NOT_ASSIGNED_DRIVER", "AUTH_REQUIRED"}

    def __init__(self, code):
        self.code = code
        self.message = self._MESSAGES.get(code, "Invalid status transition.")
        self.http_status = 403 if code in self._FORBIDDEN else 409
        super().__init__(self.message)


# ─────────────────────────────────────────────
# Create
# ─────────────────────────────────────────────
def create_request(*, client, **fields) -> ServiceRequest:
    """Create a service request in `submitted` state.

    Side effects (per §10): opening StatusHistory entry (∅ → submitted),
    activity feed event, email to the territory operator. Emails fire
    on-commit so a rolled-back create never notifies anyone.
    """
    with transaction.atomic():
        service_request = ServiceRequest.objects.create(
            client=client, status=RequestStatus.SUBMITTED, **fields,
        )
        StatusHistory.objects.create(
            request=service_request,
            from_status=None,
            to_status=RequestStatus.SUBMITTED,
            changed_by=client,
        )
        emit(
            ActivityType.ORDER_SUBMITTED,
            message=f"{client.full_name} submitted {service_request.get_service_type_display().lower()}: {service_request.title}",
            actor=client,
            target_request=service_request,
        )
        transaction.on_commit(
            lambda: notifications.send_new_request_email(service_request)
        )
    return service_request


# ─────────────────────────────────────────────
# Transition
# ─────────────────────────────────────────────
# Which timestamp field each destination status stamps.
_STATUS_TIMESTAMPS = {
    RequestStatus.ASSIGNED: "assigned_at",
    RequestStatus.IN_PROGRESS: "started_at",
    RequestStatus.COMPLETED: "completed_at",
    RequestStatus.CLOSED: "closed_at",
    RequestStatus.CANCELLED: "cancelled_at",
}

_STATUS_ACTIVITY = {
    RequestStatus.ASSIGNED: ActivityType.ORDER_ASSIGNED,
    RequestStatus.IN_PROGRESS: ActivityType.ORDER_PICKUP,
    RequestStatus.COMPLETED: ActivityType.ORDER_COMPLETED,
    RequestStatus.CANCELLED: ActivityType.ORDER_CANCELLED,
}


def _resolve_assignment_driver(service_request, driver_id):
    """Validate the driver an operator/admin is assigning.

    Must exist, hold the driver role, have an APPROVED profile, and work
    the same territory as the request's client — cross-territory dispatch
    is a business-rule violation, not a technicality.
    """
    if not driver_id:
        raise ValidationError(
            {"driver_id": ["driver_id is required when assigning a request."]},
            code="REQ_DRIVER_REQUIRED",
        )
    try:
        driver = User.objects.select_related("driver_profile").get(
            id=driver_id, role="driver",
        )
    except (User.DoesNotExist, ValueError, ValidationError):
        raise ValidationError(
            {"driver_id": ["No driver found with this id."]},
            code="REQ_DRIVER_INVALID",
        )

    profile = getattr(driver, "driver_profile", None)
    if profile is None or profile.approval_status != "approved":
        raise ValidationError(
            {"driver_id": ["This driver has not been approved yet."]},
            code="DRV_NOT_APPROVED",
        )

    client_territory_id = service_request.client.territory_id
    if (
        profile.territory_id is None
        or client_territory_id is None
        or profile.territory_id != client_territory_id
    ):
        raise ValidationError(
            {"driver_id": ["This driver works a different territory than the client."]},
            code="TERRITORY_MISMATCH",
        )
    return driver


def transition_request(
    service_request,
    *,
    new_status,
    by_user,
    driver_id=None,
    notes="",
    cancel_reason="",
    completion_notes="",
) -> ServiceRequest:
    """Move a request through the lifecycle. Single writer of `status`.

    Enforces the §10 transition matrix via the model's state machine,
    stamps the per-status timestamp, appends the StatusHistory entry,
    emits the activity event, and queues the notification emails —
    all in one transaction over a row lock (concurrent double-transitions
    lose the race cleanly instead of double-writing).
    """
    with transaction.atomic():
        # of=("self",): lock only the request row — locking across the
        # nullable driver/operator joins is a Postgres error.
        service_request = (
            ServiceRequest.objects.select_for_update(of=("self",))
            .select_related("client", "driver", "operator")
            .get(pk=service_request.pk)
        )
        old_status = service_request.status

        allowed, error_code = service_request.can_transition_to(new_status, by_user)
        if not allowed:
            raise TransitionError(error_code)

        update_fields = ["status", "updated_at"]

        if new_status == RequestStatus.REVIEWED:
            # The reviewing operator owns coordination from here on.
            if by_user.role == "operator":
                service_request.operator = by_user
                update_fields.append("operator")

        elif new_status == RequestStatus.ASSIGNED:
            service_request.driver = _resolve_assignment_driver(service_request, driver_id)
            update_fields.append("driver")
            if service_request.operator_id is None and by_user.role == "operator":
                service_request.operator = by_user
                update_fields.append("operator")

        elif new_status == RequestStatus.COMPLETED:
            if completion_notes:
                service_request.completion_notes = completion_notes
                update_fields.append("completion_notes")

        elif new_status == RequestStatus.CANCELLED:
            if not cancel_reason:
                raise ValidationError(
                    {"cancel_reason": ["cancel_reason is required when cancelling a request."]},
                    code="REQ_CANCEL_REASON_REQUIRED",
                )
            service_request.cancel_reason = cancel_reason
            update_fields.append("cancel_reason")

        timestamp_field = _STATUS_TIMESTAMPS.get(new_status)
        if timestamp_field:
            setattr(service_request, timestamp_field, timezone.now())
            update_fields.append(timestamp_field)

        service_request.status = new_status
        service_request.save(update_fields=update_fields)

        StatusHistory.objects.create(
            request=service_request,
            from_status=old_status,
            to_status=new_status,
            changed_by=by_user,
            notes=notes or cancel_reason or completion_notes,
        )

        activity_type = _STATUS_ACTIVITY.get(new_status)
        if activity_type:
            emit(
                activity_type,
                message=_activity_message(service_request, new_status, by_user),
                actor=by_user,
                target_request=service_request,
            )

        transaction.on_commit(
            lambda: notifications.send_status_update_email(service_request, old_status)
        )

    return service_request


def _activity_message(service_request, new_status, by_user):
    client_name = service_request.client.full_name
    title = service_request.title
    if new_status == RequestStatus.ASSIGNED:
        return f"{service_request.driver.full_name} assigned to {title} for {client_name}"
    if new_status == RequestStatus.IN_PROGRESS:
        return f"{by_user.full_name} started {title} for {client_name}"
    if new_status == RequestStatus.COMPLETED:
        return f"{by_user.full_name} completed {title} for {client_name}"
    if new_status == RequestStatus.CANCELLED:
        return f"{title} for {client_name} was cancelled by {by_user.full_name}"
    return f"{title} moved to {new_status}"


# ─────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────
def request_stats(user) -> dict:
    """Role-shaped dashboard counters (§10 /requests/stats/).

    Every count runs over `visible_to(user)` so the numbers can never
    leak beyond what the role is allowed to see in the list endpoint.
    """
    qs = ServiceRequest.objects.visible_to(user)
    today = timezone.localdate()

    if user.role == "client":
        return {
            "total": qs.count(),
            "active": qs.open().count(),
            "completed": qs.completed().count(),
            "cancelled": qs.filter(status=RequestStatus.CANCELLED).count(),
        }

    if user.role == "operator":
        return {
            "pending_review": qs.submitted().count(),
            "assigned": qs.assigned().count(),
            "in_progress": qs.in_progress().count(),
            "completed_today": qs.completed().filter(completed_at__date=today).count(),
        }

    if user.role == "driver":
        return {
            "assigned": qs.assigned().count(),
            "in_progress": qs.in_progress().count(),
            "completed": qs.completed().count(),
            "completed_today": qs.completed().filter(completed_at__date=today).count(),
        }

    # Admin
    from django.db.models import Count

    by_status = {status: 0 for status, _ in RequestStatus.choices}
    for row in qs.values("status").order_by().annotate(n=Count("id")):
        by_status[row["status"]] = row["n"]

    by_service_type = {}
    for row in qs.values("service_type").order_by().annotate(n=Count("id")):
        by_service_type[row["service_type"]] = row["n"]

    return {
        "total": qs.count(),
        "by_status": by_status,
        "by_service_type": by_service_type,
        "today_count": qs.filter(created_at__date=today).count(),
    }
