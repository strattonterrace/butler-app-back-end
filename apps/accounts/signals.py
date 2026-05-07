"""Post-save signals for the User model.

Two side-effects on user creation:
  1. Auto-create an inactive Subscription row for clients.
     Lets the IsActiveSubscriber gate make a real decision in M1+ — without
     this row the gate has nothing to check.
  2. Log a welcome-email intent. The actual Resend send wires in M3.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Role, User

logger = logging.getLogger("butler.accounts")


@receiver(post_save, sender=User)
def on_user_created(sender, instance, created, **kwargs):
    if not created:
        return
    # Defer side effects until the surrounding transaction commits — avoids
    # creating a Subscription pointing at a User that gets rolled back.
    transaction.on_commit(lambda: _post_create_side_effects(instance))


def _post_create_side_effects(user):
    if user.role == Role.CLIENT:
        _ensure_subscription_stub(user)

    logger.info(
        "New user registered (welcome email pending wire-up in M3): %s [%s]",
        user.email,
        user.role,
    )
    # M3 hook:
    # from apps.notifications.services import send_welcome_email
    # send_welcome_email(user)


def _ensure_subscription_stub(user):
    """Idempotent: a Subscription either exists (return) or gets created
    with status='inactive' and no Stripe IDs. M2's Stripe customer-create
    flow patches stripe_customer_id; the checkout-completed webhook flips
    status to 'active'.
    """
    from apps.subscriptions.models import Subscription, SubscriptionStatus

    Subscription.objects.get_or_create(
        user=user,
        defaults={"status": SubscriptionStatus.INACTIVE},
    )
