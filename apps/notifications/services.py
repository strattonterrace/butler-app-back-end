"""Email notification services.

M1: skeleton — log only. M3: wire Resend SMTP relay (settings.EMAIL_BACKEND
already swaps to SMTP when RESEND_API_KEY is set in production.py).
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("butler.notifications")


def _send(subject: str, body: str, to: list[str]) -> None:
    """Send an email via the configured EMAIL_BACKEND.

    In dev this prints to console. In production it routes through Resend's
    SMTP relay once RESEND_API_KEY is set.
    """
    if not to:
        logger.warning("Skipping email '%s' — no recipients", subject)
        return
    send_mail(
        subject=subject,
        message=body,
        from_email=f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>",
        recipient_list=to,
        fail_silently=True,
    )


# ── Driver application lifecycle ─────────────────────────────────────────
def send_driver_application_email(profile) -> None:
    """Tell the admins a new driver application landed."""
    from apps.accounts.models import User

    admins = User.objects.filter(role="admin", status="active")
    _send(
        subject=f"New driver application: {profile.user.full_name}",
        body=(
            f"{profile.user.full_name} applied to drive for Butler.\n\n"
            f"Vehicle: {profile.vehicle_year} {profile.vehicle_make} {profile.vehicle_model}\n"
            f"Plate: {profile.license_plate}\n\n"
            "Review it in the admin dashboard.\n\n— Butler"
        ),
        to=[a.email for a in admins],
    )


def send_driver_approved_email(profile) -> None:
    _send(
        subject="You've been approved to drive for Butler!",
        body=(
            f"Hi {profile.user.full_name},\n\n"
            "Great news — your driver application has been approved. "
            "Log in to see errands available for pickup in your territory.\n\n— Butler"
        ),
        to=[profile.user.email],
    )


def send_driver_rejected_email(profile) -> None:
    reason = profile.rejection_reason or "not specified"
    _send(
        subject="Update on your Butler driver application",
        body=(
            f"Hi {profile.user.full_name},\n\n"
            "Thank you for applying to drive for Butler. After review, we're "
            f"unable to approve your application at this time.\n\nReason: {reason}\n\n"
            "You're welcome to re-apply once addressed.\n\n— Butler"
        ),
        to=[profile.user.email],
    )


# ── Public API — called from views/signals as features land ─────────────
def send_welcome_email(user) -> None:
    _send(
        subject="Welcome to Butler",
        body=(
            f"Hi {user.full_name},\n\n"
            "Welcome to Butler. To get started, head to your account and "
            "activate your $199/month membership.\n\n— Butler"
        ),
        to=[user.email],
    )


def send_new_request_email(service_request) -> None:
    """Notify the client's territory operator(s) that a request landed.

    Falls back to every active operator when the client has no territory —
    an unroutable request is worse than a noisy inbox.
    """
    from apps.accounts.models import User

    operators = User.objects.filter(role="operator", status="active")
    if service_request.client.territory_id is not None:
        scoped = operators.filter(territory_id=service_request.client.territory_id)
        if scoped.exists():
            operators = scoped

    _send(
        subject=f"New request: {service_request.title}",
        body=(
            f"{service_request.client.full_name} submitted a new "
            f"{service_request.get_service_type_display().lower()} request.\n\n"
            f"Pickup: {service_request.pickup_location}\n"
            f"Drop-off: {service_request.dropoff_location}\n"
            f"Urgency: {service_request.get_urgency_display()}\n\n"
            "Review it in your operator dashboard.\n\n— Butler"
        ),
        to=[op.email for op in operators],
    )


# Per-status recipient + copy matrix (§10 side effects). Template polish
# (branded HTML via Resend) lands in M3 — the routing is final here.
_STATUS_EMAILS = {
    "reviewed": {
        "to": ("client",),
        "subject": "Your Butler request is being reviewed",
        "body": "Good news — our team is reviewing \"{title}\" and will assign a driver shortly.",
    },
    "assigned": {
        "to": ("client", "driver"),
        "subject": "A driver has been assigned to your request",
        "body": "\"{title}\" has been assigned to {driver_name}. You'll be notified when your errand is underway.",
    },
    "in_progress": {
        "to": ("client",),
        "subject": "Your errand is in progress",
        "body": "{driver_name} has started \"{title}\". Sit back — we've got it from here.",
    },
    "completed": {
        "to": ("client",),
        "subject": "Your errand is complete!",
        "body": "\"{title}\" is done. Consider tipping your driver, {driver_name}, from the request page.",
    },
    "cancelled": {
        "to": ("client", "driver"),
        "subject": "Request cancelled",
        "body": "\"{title}\" has been cancelled. Reason: {cancel_reason}",
    },
}


def send_status_update_email(service_request, old_status) -> None:
    """Route lifecycle-change emails per the §10 side-effect matrix."""
    spec = _STATUS_EMAILS.get(service_request.status)
    if spec is None:
        return

    recipients = []
    if "client" in spec["to"]:
        recipients.append(service_request.client.email)
    if "driver" in spec["to"] and service_request.driver is not None:
        recipients.append(service_request.driver.email)

    driver_name = (
        service_request.driver.full_name if service_request.driver else "your driver"
    )
    body = spec["body"].format(
        title=service_request.title,
        driver_name=driver_name,
        cancel_reason=service_request.cancel_reason or "not specified",
    )
    _send(
        subject=spec["subject"],
        body=f"{body}\n\n— Butler",
        to=recipients,
    )
