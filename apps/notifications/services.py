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


def send_request_status_email(request, recipient) -> None:
    """Wired in M3 once status-transition endpoints exist."""
    logger.info(
        "send_request_status_email pending wire-up: req=%s status=%s to=%s",
        request.id, request.status, recipient.email,
    )
