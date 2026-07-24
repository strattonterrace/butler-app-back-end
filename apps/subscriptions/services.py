"""Stripe subscription services — M2 business logic.

Views stay thin: they parse input, delegate here, and serialise output.
All Stripe SDK calls are concentrated in this module so the rest of the
codebase never imports stripe directly (webhooks.py consumes the events
Stripe sends back and calls sync helpers defined here).

Money flow (single $199/month plan):
  1. Client registers → Subscription stub (status=inactive), no Stripe IDs.
  2. Client hits create-checkout → we lazily ensure a Stripe Customer,
     then open a Checkout Session for STRIPE_PRICE_ID.
  3. Stripe redirects back to the frontend; the *webhook* — not the
     redirect — is the source of truth that flips status to 'active'.
  4. Cancel/reactivate mutate cancel_at_period_end on Stripe and mirror
     locally; the subscription.updated webhook reconciles authoritatively.
"""
import logging
from datetime import datetime, timezone as dt_timezone
from typing import Optional

import stripe
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Subscription, SubscriptionStatus

logger = logging.getLogger("butler.subscriptions")


class StripeNotConfigured(Exception):
    """Raised when a Stripe call is attempted without API keys set."""


def _stripe():
    """Return the configured stripe module, failing fast if keys are absent."""
    if not settings.STRIPE_SECRET_KEY:
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set.")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


# Stripe subscription statuses → local SubscriptionStatus.
# 'trialing' maps to active (we don't offer trials, but if one is ever
# comped via the Stripe dashboard the client shouldn't be locked out).
_STRIPE_STATUS_MAP = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.ACTIVE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELLED,
    "incomplete": SubscriptionStatus.INCOMPLETE,
    "incomplete_expired": SubscriptionStatus.INCOMPLETE,
    "paused": SubscriptionStatus.INACTIVE,
}


# ─────────────────────────────────────────────
# Public API — call these from views / accounts services
# ─────────────────────────────────────────────
def get_or_create_subscription(user) -> Subscription:
    """Every client owns exactly one Subscription row. The registration
    signal normally creates it; this covers pre-signal legacy rows."""
    sub, _ = Subscription.objects.get_or_create(
        user=user, defaults={"status": SubscriptionStatus.INACTIVE},
    )
    return sub


def ensure_stripe_customer(user) -> str:
    """Return the user's Stripe customer id, creating the Customer lazily.

    Lazy-at-checkout (rather than eager-at-register) means registration
    never blocks on a Stripe network call and dev environments without
    keys keep working.
    """
    sub = get_or_create_subscription(user)
    if sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer = _stripe().Customer.create(
        email=user.email,
        name=user.full_name,
        metadata={"butler_user_id": str(user.id)},
    )
    sub.stripe_customer_id = customer["id"]
    sub.save(update_fields=["stripe_customer_id", "updated_at"])
    logger.info("stripe customer created: %s → %s", user.email, customer["id"])
    return customer["id"]


def create_checkout_session(user) -> str:
    """Open a Stripe Checkout Session for the $199/month plan. Returns the
    hosted checkout URL the frontend redirects to."""
    sub = get_or_create_subscription(user)
    if sub.is_active:
        raise ValidationError(
            {"detail": "You already have an active subscription."},
            code="SUB_ALREADY_ACTIVE",
        )

    customer_id = ensure_stripe_customer(user)
    session = _stripe().checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
        success_url=f"{settings.FRONTEND_URL}/dashboard?subscription=success",
        cancel_url=f"{settings.FRONTEND_URL}/subscribe?cancelled=true",
        client_reference_id=str(user.id),
    )
    logger.info("checkout session opened: %s", user.email)
    return session["url"]


def create_portal_session(user) -> str:
    """Stripe Customer Portal — payment method updates + invoice history."""
    sub = get_or_create_subscription(user)
    if not sub.stripe_customer_id:
        raise ValidationError(
            {"detail": "No billing profile yet — subscribe first."},
            code="SUB_NOT_ACTIVE",
        )
    session = _stripe().billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{settings.FRONTEND_URL}/settings",
    )
    return session["url"]


def cancel_subscription(user) -> Subscription:
    """Cancel at period end. The client keeps access until
    current_period_end; the subscription.deleted webhook finalises."""
    sub = get_or_create_subscription(user)
    if not sub.is_active:
        raise ValidationError(
            {"detail": "No active subscription to cancel."},
            code="SUB_NOT_ACTIVE",
        )
    if sub.stripe_subscription_id:
        _stripe().Subscription.modify(
            sub.stripe_subscription_id, cancel_at_period_end=True,
        )
    sub.cancel_at_period_end = True
    sub.cancelled_at = timezone.now()
    sub.save(update_fields=["cancel_at_period_end", "cancelled_at", "updated_at"])
    logger.info("subscription set to cancel at period end: %s", user.email)
    return sub


def reactivate_subscription(user) -> Subscription:
    """Undo a pending cancellation before the period ends."""
    sub = get_or_create_subscription(user)
    if not (sub.is_active and sub.cancel_at_period_end):
        raise ValidationError(
            {"detail": "No pending cancellation to reactivate."},
            code="SUB_NOT_CANCELLING",
        )
    if sub.stripe_subscription_id:
        _stripe().Subscription.modify(
            sub.stripe_subscription_id, cancel_at_period_end=False,
        )
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    sub.save(update_fields=["cancel_at_period_end", "cancelled_at", "updated_at"])
    logger.info("subscription reactivated: %s", user.email)
    return sub


def cancel_subscription_best_effort(user) -> None:
    """Suspension/self-delete path: always mark the local row to cancel at
    period end; treat the Stripe call as best-effort so account actions
    never fail because Stripe is down or unconfigured. A failed remote
    cancel is logged loudly for manual follow-up."""
    sub = Subscription.objects.filter(user=user).first()
    if sub is None:
        return
    if sub.stripe_subscription_id:
        try:
            _stripe().Subscription.modify(
                sub.stripe_subscription_id, cancel_at_period_end=True,
            )
        except (StripeNotConfigured, stripe.StripeError) as exc:
            logger.error(
                "stripe cancel failed for %s (%s) — cancel manually in the "
                "Stripe dashboard: %s",
                user.email, sub.stripe_subscription_id, exc,
            )
    if sub.is_active and not sub.cancel_at_period_end:
        sub.cancel_at_period_end = True
        sub.cancelled_at = timezone.now()
        sub.save(update_fields=["cancel_at_period_end", "cancelled_at", "updated_at"])


# ─────────────────────────────────────────────
# Webhook sync helpers — called from webhooks.py with verified event data
# ─────────────────────────────────────────────
def _epoch_to_dt(value) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)


def _extract_period(stripe_sub: dict):
    """Billing period start/end. Newer Stripe API versions moved these from
    the Subscription onto its items — check both shapes."""
    start = stripe_sub.get("current_period_start")
    end = stripe_sub.get("current_period_end")
    if start is None or end is None:
        items = (stripe_sub.get("items") or {}).get("data") or []
        if items:
            start = start if start is not None else items[0].get("current_period_start")
            end = end if end is not None else items[0].get("current_period_end")
    return _epoch_to_dt(start), _epoch_to_dt(end)


def find_subscription_for_event(*, customer_id=None, subscription_id=None,
                                user_id=None) -> Optional[Subscription]:
    """Locate the local row for a webhook payload, most specific key first."""
    if subscription_id:
        sub = Subscription.objects.filter(
            stripe_subscription_id=subscription_id).first()
        if sub:
            return sub
    if customer_id:
        sub = Subscription.objects.filter(stripe_customer_id=customer_id).first()
        if sub:
            return sub
    if user_id:
        return Subscription.objects.filter(user_id=user_id).first()
    return None


def sync_subscription_from_stripe(local: Subscription, stripe_sub: dict) -> Subscription:
    """Mirror an authoritative Stripe Subscription object onto the local row."""
    new_status = _STRIPE_STATUS_MAP.get(
        stripe_sub.get("status"), local.status,
    )
    period_start, period_end = _extract_period(stripe_sub)

    local.stripe_subscription_id = stripe_sub.get("id") or local.stripe_subscription_id
    local.status = new_status
    local.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end"))
    local.cancelled_at = _epoch_to_dt(stripe_sub.get("canceled_at"))
    if period_start:
        local.current_period_start = period_start
    if period_end:
        local.current_period_end = period_end
    local.save()
    return local
