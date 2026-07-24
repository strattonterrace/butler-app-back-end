"""Stripe webhook processing.

The webhook — not the checkout redirect — is the source of truth for
subscription state. Stripe retries failed deliveries, may deliver the
same event more than once, and does not guarantee ordering, so every
handler here is a pure idempotent sync: it reads the event payload and
converges the local row toward it.

Signature verification and the idempotency ledger live in the view
(views.StripeWebhookView); this module assumes it receives an already
verified `stripe.Event`-shaped dict.
"""
import logging

from apps.activity.services import ActivityType, emit

from . import services
from .models import SubscriptionStatus

logger = logging.getLogger("butler.subscriptions")


def process_event(event) -> bool:
    """Dispatch a verified Stripe event. Returns True if the event type is
    one we handle, False if it was ignored (still a 200 to Stripe)."""
    handler = _HANDLED_EVENTS.get(event["type"])
    if handler is None:
        logger.info("stripe event ignored: %s", event["type"])
        return False
    handler(event["data"]["object"])
    return True


# ─────────────────────────────────────────────
# Handlers — one per event type
# ─────────────────────────────────────────────
def _handle_checkout_completed(session):
    """checkout.session.completed — the client finished paying.

    Activates immediately so the client isn't blocked waiting for the
    subsequent customer.subscription.* events (which carry the billing
    period and reconcile authoritatively moments later).
    """
    sub = services.find_subscription_for_event(
        customer_id=session.get("customer"),
        user_id=session.get("client_reference_id"),
    )
    if sub is None:
        logger.error(
            "checkout completed but no local subscription found: customer=%s ref=%s",
            session.get("customer"), session.get("client_reference_id"),
        )
        return

    if not sub.stripe_customer_id and session.get("customer"):
        sub.stripe_customer_id = session["customer"]
    if session.get("subscription"):
        sub.stripe_subscription_id = session["subscription"]
    was_active = sub.is_active
    sub.status = SubscriptionStatus.ACTIVE
    sub.save()

    if not was_active:
        emit(
            ActivityType.SUBSCRIPTION_NEW,
            message=f"{sub.user.full_name} activated a Butler membership",
            actor=sub.user,
        )
    logger.info("subscription activated via checkout: %s", sub.user.email)


def _handle_subscription_upsert(stripe_sub):
    """customer.subscription.created / .updated — authoritative sync of
    status, billing period, and cancel_at_period_end."""
    sub = services.find_subscription_for_event(
        subscription_id=stripe_sub.get("id"),
        customer_id=stripe_sub.get("customer"),
    )
    if sub is None:
        logger.error(
            "subscription event for unknown customer: %s", stripe_sub.get("customer"),
        )
        return

    old_status = sub.status
    services.sync_subscription_from_stripe(sub, stripe_sub)

    if old_status != sub.status and sub.status == SubscriptionStatus.PAST_DUE:
        # Payment-issue email lands in M3; the activity feed records it now.
        emit(
            ActivityType.PAYMENT_FAILED,
            message=f"Subscription for {sub.user.full_name} is past due",
            actor=sub.user,
        )
    logger.info(
        "subscription synced: %s %s → %s", sub.user.email, old_status, sub.status,
    )


def _handle_subscription_deleted(stripe_sub):
    """customer.subscription.deleted — the subscription fully ended
    (period ran out after a cancel, or was cancelled immediately)."""
    sub = services.find_subscription_for_event(
        subscription_id=stripe_sub.get("id"),
        customer_id=stripe_sub.get("customer"),
    )
    if sub is None:
        logger.error(
            "subscription.deleted for unknown subscription: %s", stripe_sub.get("id"),
        )
        return

    was_cancelled = sub.status == SubscriptionStatus.CANCELLED
    services.sync_subscription_from_stripe(sub, stripe_sub)
    sub.status = SubscriptionStatus.CANCELLED
    sub.save(update_fields=["status", "updated_at"])

    if not was_cancelled:
        emit(
            ActivityType.SUBSCRIPTION_CANCELLED,
            message=f"{sub.user.full_name}'s membership ended",
            actor=sub.user,
        )
    logger.info("subscription cancelled: %s", sub.user.email)


def _handle_payment_succeeded(invoice):
    """invoice.payment_succeeded — recovery path. A past_due/incomplete
    subscription whose retry succeeds flips back to active here."""
    sub = services.find_subscription_for_event(
        subscription_id=_invoice_subscription_id(invoice),
        customer_id=invoice.get("customer"),
    )
    if sub is None:
        return
    if sub.status in (
        SubscriptionStatus.PAST_DUE,
        SubscriptionStatus.INCOMPLETE,
        SubscriptionStatus.INACTIVE,
    ):
        sub.status = SubscriptionStatus.ACTIVE
        sub.save(update_fields=["status", "updated_at"])
        logger.info("subscription recovered to active: %s", sub.user.email)


def _handle_payment_failed(invoice):
    """invoice.payment_failed — card declined/expired. Access degrades to
    past_due; Stripe keeps retrying per its dunning schedule."""
    sub = services.find_subscription_for_event(
        subscription_id=_invoice_subscription_id(invoice),
        customer_id=invoice.get("customer"),
    )
    if sub is None:
        return
    if sub.status != SubscriptionStatus.PAST_DUE:
        sub.status = SubscriptionStatus.PAST_DUE
        sub.save(update_fields=["status", "updated_at"])
        emit(
            ActivityType.PAYMENT_FAILED,
            message=f"Payment failed for {sub.user.full_name}",
            actor=sub.user,
        )
    logger.warning("payment failed: %s", sub.user.email)


def _invoice_subscription_id(invoice):
    """Invoice → subscription id across Stripe API versions: older ones put
    it at invoice.subscription, newer under parent.subscription_details."""
    sub_id = invoice.get("subscription")
    if sub_id:
        return sub_id
    parent = invoice.get("parent") or {}
    details = parent.get("subscription_details") or {}
    return details.get("subscription")


_HANDLED_EVENTS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.created": _handle_subscription_upsert,
    "customer.subscription.updated": _handle_subscription_upsert,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_succeeded": _handle_payment_succeeded,
    "invoice.payment_failed": _handle_payment_failed,
}
