"""Email notification services — branded HTML emails via Resend (M3).

Transport: Django's EmailMultiAlternatives over the configured EMAIL_BACKEND.
In production that backend is Resend's SMTP relay (auto-enabled once
RESEND_API_KEY is set — see production.py); in dev it prints to the console.
Every email ships both an HTML part (templates/emails/base.html) and a plain
text part (base.txt) for deliverability and accessibility.

Design rule: sending must never break the request flow. These are invoked via
transaction.on_commit from the service layer, and _send swallows+logs any SMTP
error rather than raising.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger("butler.notifications")


# ─────────────────────────────────────────────
# Core sender
# ─────────────────────────────────────────────
def _first_name(user) -> str:
    return (user.full_name or "there").split(" ")[0]


def _url(path: str = "") -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/{path.lstrip('/')}" if path else base


def _send(*, to, subject, heading, intro="", body_lines=None,
          info_rows=None, cta=None, outro="", preheader="") -> None:
    """Render the branded template and send one email.

    `cta` is {"text", "url"}; `info_rows` is a list of {"label", "value"}.
    Never raises — SMTP failures are logged, not propagated.
    """
    recipients = [e for e in (to or []) if e]
    if not recipients:
        logger.warning("Skipping email '%s' — no recipients", subject)
        return

    frontend = settings.FRONTEND_URL.rstrip("/")
    context = {
        "subject": subject,
        "preheader": preheader or (body_lines[0] if body_lines else heading),
        "heading": heading,
        "intro": intro,
        "body_lines": body_lines or [],
        "info_rows": info_rows or [],
        "cta": cta,
        "outro": outro,
        "frontend_url": frontend,
        "frontend_url_display": frontend.split("://")[-1],
    }
    html_body = render_to_string("emails/base.html", context)
    text_body = render_to_string("emails/base.txt", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>",
        to=recipients,
    )
    message.attach_alternative(html_body, "text/html")
    try:
        message.send(fail_silently=False)
        logger.info("email sent: '%s' → %s", subject, recipients)
    except Exception:
        logger.warning("email send failed: '%s' → %s", subject, recipients, exc_info=True)


# ─────────────────────────────────────────────
# Account lifecycle
# ─────────────────────────────────────────────
def send_welcome_email(user) -> None:
    _send(
        to=[user.email],
        subject="Welcome to Butler",
        heading="Welcome to Butler",
        intro=f"Hi {_first_name(user)},",
        body_lines=[
            "You're one step from handing off your errands. Activate your membership "
            "and your personal concierge is on call.",
            "Groceries, pharmacy runs, dry cleaning, packages — just ask, and we handle it.",
        ],
        cta={"text": "Activate your membership", "url": _url("subscribe")},
        outro="Welcome aboard.",
        preheader="Activate your membership and your concierge is on call.",
    )


def send_password_reset_email(user, reset_url: str) -> None:
    _send(
        to=[user.email],
        subject="Reset your Butler password",
        heading="Reset your password",
        intro=f"Hi {_first_name(user)},",
        body_lines=[
            "We received a request to reset your password. Click the button below "
            "to choose a new one — the link expires shortly for your security.",
            "If you didn't request this, you can safely ignore this email; your "
            "password won't change.",
        ],
        cta={"text": "Reset password", "url": reset_url},
        preheader="Reset your Butler password.",
    )


# ─────────────────────────────────────────────
# Request lifecycle
# ─────────────────────────────────────────────
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
        to=[op.email for op in operators],
        subject=f"New request: {service_request.title}",
        heading="New request in your territory",
        body_lines=[
            f"{service_request.client.full_name} just submitted a new "
            f"{service_request.get_service_type_display().lower()} request.",
        ],
        info_rows=[
            {"label": "Service", "value": service_request.get_service_type_display()},
            {"label": "Pickup", "value": service_request.pickup_location},
            {"label": "Drop-off", "value": service_request.dropoff_location},
            {"label": "Urgency", "value": service_request.get_urgency_display()},
        ],
        cta={"text": "Review in dashboard", "url": _url("operator/queue")},
        preheader=f"{service_request.client.full_name} submitted a new request.",
    )


# Per-status copy. Recipients routed to role-appropriate links below.
_STATUS_EMAILS = {
    "reviewed": {
        "to": ("client",),
        "subject": "Your Butler request is being reviewed",
        "heading": "We're on it",
        "lines": ['Our team is reviewing "{title}" and will assign a driver shortly.'],
    },
    "assigned": {
        "to": ("client", "driver"),
        "subject": "A driver has been assigned to your request",
        "heading": "Your driver is assigned",
        "lines": [
            '"{title}" has been assigned to {driver_name}. '
            "You'll get another note when your errand is underway.",
        ],
    },
    "in_progress": {
        "to": ("client",),
        "subject": "Your errand is in progress",
        "heading": "Your errand is underway",
        "lines": ['{driver_name} has started "{title}". Sit back — we\'ve got it from here.'],
    },
    "completed": {
        "to": ("client",),
        "subject": "Your errand is complete",
        "heading": "All done",
        "lines": [
            '"{title}" is complete. If {driver_name} did a great job, you can add a '
            "tip from the request page.",
        ],
    },
    "cancelled": {
        "to": ("client", "driver"),
        "subject": "Request cancelled",
        "heading": "Request cancelled",
        "lines": ['"{title}" has been cancelled.', "Reason: {cancel_reason}"],
    },
}


def send_status_update_email(service_request, old_status) -> None:
    """Route lifecycle-change emails per the status matrix.

    Client and driver each get the email with a link into *their* view of the
    request, so the CTA always lands somewhere they can actually use.
    """
    spec = _STATUS_EMAILS.get(service_request.status)
    if spec is None:
        return

    driver_name = (
        service_request.driver.full_name if service_request.driver else "your driver"
    )
    lines = [
        line.format(
            title=service_request.title,
            driver_name=driver_name,
            cancel_reason=service_request.cancel_reason or "not specified",
        )
        for line in spec["lines"]
    ]

    if "client" in spec["to"]:
        _send(
            to=[service_request.client.email],
            subject=spec["subject"],
            heading=spec["heading"],
            intro=f"Hi {_first_name(service_request.client)},",
            body_lines=lines,
            cta={"text": "View your request", "url": _url(f"requests/{service_request.id}")},
        )
    if "driver" in spec["to"] and service_request.driver is not None:
        _send(
            to=[service_request.driver.email],
            subject=spec["subject"],
            heading=spec["heading"],
            intro=f"Hi {_first_name(service_request.driver)},",
            body_lines=lines,
            cta={"text": "View your task", "url": _url(f"driver/tasks/{service_request.id}")},
        )


# ─────────────────────────────────────────────
# Driver application lifecycle
# ─────────────────────────────────────────────
def send_driver_application_email(profile) -> None:
    """Tell the admins a new driver application landed."""
    from apps.accounts.models import User

    admins = User.objects.filter(role="admin", status="active")
    _send(
        to=[a.email for a in admins],
        subject=f"New driver application: {profile.user.full_name}",
        heading="New driver application",
        body_lines=[f"{profile.user.full_name} applied to drive for Butler."],
        info_rows=[
            {"label": "Driver", "value": profile.user.full_name},
            {"label": "Vehicle", "value": f"{profile.vehicle_year} {profile.vehicle_make} {profile.vehicle_model}"},
            {"label": "Plate", "value": profile.license_plate},
        ],
        cta={"text": "Review application", "url": _url("admin/drivers")},
        preheader=f"{profile.user.full_name} applied to drive for Butler.",
    )


def send_driver_approved_email(profile) -> None:
    _send(
        to=[profile.user.email],
        subject="You're approved to drive for Butler!",
        heading="You're approved!",
        intro=f"Hi {_first_name(profile.user)},",
        body_lines=[
            "Great news — your driver application has been approved. You can now be "
            "assigned errands in your territory.",
            "Log in to see your tasks and get started.",
        ],
        cta={"text": "Open your dashboard", "url": _url("driver")},
        outro="Welcome to the team.",
        preheader="Your Butler driver application was approved.",
    )


def send_driver_rejected_email(profile) -> None:
    reason = profile.rejection_reason or "not specified"
    _send(
        to=[profile.user.email],
        subject="Update on your Butler driver application",
        heading="About your application",
        intro=f"Hi {_first_name(profile.user)},",
        body_lines=[
            "Thank you for applying to drive for Butler. After review, we're unable "
            "to approve your application at this time.",
            f"Reason: {reason}",
            "You're welcome to re-apply once that's addressed.",
        ],
        preheader="An update on your Butler driver application.",
    )
