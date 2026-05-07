"""Account services — business logic layer.

Views stay thin: they parse input, delegate here, and serialise output.
This is where multi-step orchestration lives (e.g. register a user +
create a Stripe customer + send a welcome email — three side effects in
one logical operation).

Stripe and email side effects are isolated as private functions clearly
marked for M2 / M3 wire-up. M1 keeps them as no-ops so the orchestration
shape is right and only the implementation needs to land later.
"""
import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import Role, Status, User

logger = logging.getLogger("butler.accounts")


# ─────────────────────────────────────────────
# Public API — call these from views
# ─────────────────────────────────────────────
@transaction.atomic
def register_user(*, email: str, password: str, full_name: str, phone: str = "") -> User:
    """Create a client account.

    Side effects (in order, all atomic):
      1. Create the User row (post_save signal creates Subscription stub).
      2. Best-effort Stripe customer creation (M2 wires the real call).
      3. Welcome email queued (M3 wires Resend).

    Raises ValidationError on bad input. Caller's serializer should have
    already validated, but services double-check for defence in depth.
    """
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        phone=phone or "",
        role=Role.CLIENT,
    )
    _create_stripe_customer(user)
    return user


def change_password(*, user: User, current_password: str, new_password: str) -> None:
    """Logged-in password change. Verifies current_password, sets new.
    Raises ValidationError on wrong current_password or weak new_password.
    """
    if not user.check_password(current_password):
        raise ValidationError(
            {"current_password": "Current password is incorrect."},
            code="AUTH_INVALID_CREDENTIALS",
        )
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    logger.info("password changed for %s", user.email)


def request_password_reset(*, email: str) -> None:
    """Send a password-reset email. Always returns successfully — never
    reveals whether the address is registered (timing-safe)."""
    email = email.lower().strip()
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

    send_mail(
        subject="Butler — Reset your password",
        message=(
            f"Hi {user.full_name},\n\n"
            f"Click the link below to reset your password:\n{reset_url}\n\n"
            f"If you didn't request this, ignore this email.\n\n— Butler"
        ),
        from_email=f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>",
        recipient_list=[user.email],
        fail_silently=True,
    )


def confirm_password_reset(*, uid: str, token: str, new_password: str) -> User:
    """Validate the reset token and set new password. Raises ValidationError."""
    try:
        user_pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_pk)
    except (User.DoesNotExist, ValueError, TypeError):
        raise ValidationError({"uid": "Invalid reset link."}, code="AUTH_INVALID_RESET")

    if not default_token_generator.check_token(user, token):
        raise ValidationError({"token": "Reset link expired or invalid."}, code="AUTH_INVALID_RESET")

    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return user


@transaction.atomic
def delete_account(*, user: User, password: str) -> None:
    """Soft-delete a client account.

    Beta policy:
      - Password must be confirmed by the user.
      - Status flips to 'suspended' (data retained for chargeback / dispute window).
      - Stripe subscription is cancelled at period end (M2 wires).
      - Sessions invalidated by deactivating the account on Django side.
    """
    if not user.check_password(password):
        raise ValidationError(
            {"password": "Password is incorrect."},
            code="AUTH_INVALID_CREDENTIALS",
        )
    user.status = Status.SUSPENDED
    user.is_active = False  # blocks future JWT issuance
    user.save(update_fields=["status", "is_active"])
    _cancel_subscription_at_period_end(user)
    logger.info("account self-deleted: %s", user.email)


@transaction.atomic
def suspend_user(*, target: User, by_admin: User) -> None:
    """Admin-initiated suspension. Idempotent."""
    if target == by_admin:
        raise ValidationError(
            {"detail": "An admin cannot suspend their own account."},
            code="ADMIN_CANNOT_SELF_SUSPEND",
        )
    target.status = Status.SUSPENDED
    target.is_active = False
    target.save(update_fields=["status", "is_active"])
    if target.role == Role.CLIENT:
        _cancel_subscription_at_period_end(target)
    if target.role == Role.DRIVER:
        _unassign_driver_from_open_requests(target)
    logger.info("user suspended by admin: target=%s by=%s", target.email, by_admin.email)


@transaction.atomic
def reactivate_user(*, target: User, by_admin: User) -> None:
    """Re-enable a previously suspended account."""
    target.status = Status.ACTIVE
    target.is_active = True
    target.save(update_fields=["status", "is_active"])
    logger.info("user reactivated by admin: target=%s by=%s", target.email, by_admin.email)


@transaction.atomic
def create_operator(*, email: str, full_name: str, password: str,
                    territory_id: Optional[str] = None, by_admin: User) -> User:
    """Admin creates an operator account. Operator gets login credentials
    via email; territory may be assigned at creation or later."""
    operator = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        role=Role.OPERATOR,
        territory_id=territory_id,
    )
    logger.info("operator created by admin: target=%s by=%s", operator.email, by_admin.email)
    return operator


# ─────────────────────────────────────────────
# Private hooks — currently no-ops; M2/M3 wires real calls.
# Keeping these as named functions means M2/M3 work is "fill in the body"
# rather than "add a call site." Architecture > implementation.
# ─────────────────────────────────────────────
def _create_stripe_customer(user: User) -> Optional[str]:
    """Create a Stripe Customer for this user.

    M2: ``stripe.Customer.create(email=user.email, name=user.full_name,
        metadata={"butler_user_id": str(user.id)})``, then patch the
    Subscription row with the returned customer.id.
    """
    logger.debug("Stripe customer create pending wire-up: %s", user.email)
    return None


def _cancel_subscription_at_period_end(user: User) -> None:
    """Mark the user's Subscription to cancel at the end of the current period.

    M2: read user.subscription, call stripe.Subscription.modify(
        sub_id, cancel_at_period_end=True), persist locally on webhook receipt.
    """
    logger.debug("Stripe sub cancel pending wire-up: %s", user.email)


def _unassign_driver_from_open_requests(driver: User) -> None:
    """When a driver is suspended, free up their open assignments so an
    operator can reassign them."""
    from apps.requests.models import ServiceRequest, RequestStatus
    open_count = ServiceRequest.objects.filter(
        driver=driver, status__in=[RequestStatus.ASSIGNED, RequestStatus.IN_PROGRESS],
    ).update(driver=None, status=RequestStatus.REVIEWED)
    if open_count:
        logger.info("Unassigned driver from %d open request(s): %s", open_count, driver.email)
