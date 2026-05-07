"""Activity feed emit helper.

One-line API for M3 lifecycle code:

    from apps.activity.services import emit, ActivityType

    emit(
        ActivityType.ORDER_ASSIGNED,
        message=f"{driver.full_name} assigned to {request.title}",
        actor=operator,
        target_request=request,
    )

Failures are swallowed and logged — telemetry must never break a request.
"""
import logging
from typing import Optional

from .models import ActivityLog, ActivityType  # re-export for callers

logger = logging.getLogger("butler.activity")


def emit(
    event_type: str,
    *,
    message: str,
    actor=None,
    target_request=None,
    **metadata,
) -> Optional[ActivityLog]:
    """Append an event to the ActivityLog. Returns the created row or None
    on failure. Never raises — telemetry is never load-bearing on a request.

    Parameters
    ----------
    event_type : str
        One of ActivityType values (use the enum to get autocomplete).
    message : str
        Pre-rendered display string (matches MOCK_ACTIVITY.message shape).
    actor : User, optional
        The user whose action triggered this event.
    target_request : ServiceRequest, optional
        The request this event relates to, if any.
    **metadata
        Free-form fields stored in the JSONField for event-specific data
        (rating value, tip amount, dispute reason, etc).
    """
    try:
        return ActivityLog.objects.create(
            type=event_type,
            message=message,
            actor=actor,
            target_request=target_request,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "ActivityLog emit failed: type=%s message=%r", event_type, message,
        )
        return None


__all__ = ["emit", "ActivityType"]
