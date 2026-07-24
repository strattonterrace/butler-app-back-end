"""Stripe webhook intake — POST /api/v1/subscriptions/webhook/.

stripe.Webhook.construct_event is patched to return canned events; the
view's signature check and the handlers' state transitions are exercised
against real database rows.
"""
import json
from unittest.mock import patch

import pytest
import stripe

from apps.activity.models import ActivityLog, ActivityType
from apps.subscriptions.models import (
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/subscriptions/webhook/"

PERIOD_START = 1782000000  # arbitrary epoch seconds
PERIOD_END = 1784678400


def post_event(api_client, event):
    """POST a canned event past signature verification."""
    with patch("stripe.Webhook.construct_event", return_value=event):
        return api_client.post(
            URL,
            data=json.dumps(event),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=test",
        )


def make_event(event_id, event_type, obj):
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


@pytest.fixture
def inactive_sub(client_user):
    return Subscription.objects.create(
        user=client_user,
        status=SubscriptionStatus.INACTIVE,
        stripe_customer_id="cus_123",
    )


@pytest.fixture
def active_sub(client_user):
    return Subscription.objects.create(
        user=client_user,
        status=SubscriptionStatus.ACTIVE,
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
    )


class TestWebhookSecurity:
    def test_invalid_signature_rejected(self, api_client):
        with patch(
            "stripe.Webhook.construct_event",
            side_effect=stripe.SignatureVerificationError("bad", "sig"),
        ):
            resp = api_client.post(
                URL, data="{}", content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=1,v1=forged",
            )
        assert resp.status_code == 400
        assert resp.json()["code"] == "WEBHOOK_INVALID"

    def test_malformed_payload_rejected(self, api_client):
        with patch(
            "stripe.Webhook.construct_event", side_effect=ValueError("not json"),
        ):
            resp = api_client.post(
                URL, data="garbage", content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=1,v1=x",
            )
        assert resp.status_code == 400

    def test_duplicate_event_processed_once(self, api_client, inactive_sub):
        event = make_event("evt_dup", "checkout.session.completed", {
            "customer": "cus_123", "subscription": "sub_123",
            "client_reference_id": str(inactive_sub.user_id),
        })
        first = post_event(api_client, event)
        second = post_event(api_client, event)

        assert first.status_code == 200
        assert second.json()["duplicate"] is True
        assert WebhookEvent.objects.filter(stripe_event_id="evt_dup").count() == 1
        assert ActivityLog.objects.filter(
            type=ActivityType.SUBSCRIPTION_NEW).count() == 1

    def test_unhandled_event_type_acknowledged(self, api_client):
        event = make_event("evt_odd", "charge.refunded", {})
        resp = post_event(api_client, event)
        assert resp.status_code == 200
        assert resp.json()["handled"] is False


class TestCheckoutCompleted:
    def test_activates_subscription(self, api_client, inactive_sub):
        event = make_event("evt_1", "checkout.session.completed", {
            "customer": "cus_123",
            "subscription": "sub_new",
            "client_reference_id": str(inactive_sub.user_id),
        })
        resp = post_event(api_client, event)
        assert resp.status_code == 200

        inactive_sub.refresh_from_db()
        assert inactive_sub.status == SubscriptionStatus.ACTIVE
        assert inactive_sub.stripe_subscription_id == "sub_new"
        assert ActivityLog.objects.filter(
            type=ActivityType.SUBSCRIPTION_NEW, actor=inactive_sub.user).exists()

    def test_falls_back_to_client_reference_id(self, api_client, client_user):
        # Row exists but has no customer id yet (eager create never ran)
        sub = Subscription.objects.create(
            user=client_user, status=SubscriptionStatus.INACTIVE,
        )
        event = make_event("evt_2", "checkout.session.completed", {
            "customer": "cus_fresh",
            "subscription": "sub_fresh",
            "client_reference_id": str(client_user.id),
        })
        post_event(api_client, event)

        sub.refresh_from_db()
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.stripe_customer_id == "cus_fresh"

    def test_unknown_customer_is_acknowledged_not_500(self, api_client):
        event = make_event("evt_3", "checkout.session.completed", {
            "customer": "cus_ghost", "subscription": "sub_x",
            "client_reference_id": None,
        })
        assert post_event(api_client, event).status_code == 200


class TestSubscriptionSync:
    def test_updated_syncs_status_and_period(self, api_client, active_sub):
        event = make_event("evt_4", "customer.subscription.updated", {
            "id": "sub_123",
            "customer": "cus_123",
            "status": "active",
            "cancel_at_period_end": True,
            "canceled_at": PERIOD_START,
            "current_period_start": PERIOD_START,
            "current_period_end": PERIOD_END,
        })
        post_event(api_client, event)

        active_sub.refresh_from_db()
        assert active_sub.cancel_at_period_end is True
        assert active_sub.cancelled_at is not None
        assert int(active_sub.current_period_start.timestamp()) == PERIOD_START
        assert int(active_sub.current_period_end.timestamp()) == PERIOD_END

    def test_updated_reads_period_from_items_shape(self, api_client, active_sub):
        # Newer Stripe API versions carry the billing period on items
        event = make_event("evt_5", "customer.subscription.updated", {
            "id": "sub_123",
            "customer": "cus_123",
            "status": "active",
            "cancel_at_period_end": False,
            "items": {"data": [{
                "current_period_start": PERIOD_START,
                "current_period_end": PERIOD_END,
            }]},
        })
        post_event(api_client, event)

        active_sub.refresh_from_db()
        assert int(active_sub.current_period_end.timestamp()) == PERIOD_END

    def test_transition_to_past_due_emits_activity(self, api_client, active_sub):
        event = make_event("evt_6", "customer.subscription.updated", {
            "id": "sub_123", "customer": "cus_123", "status": "past_due",
            "cancel_at_period_end": False,
        })
        post_event(api_client, event)

        active_sub.refresh_from_db()
        assert active_sub.status == SubscriptionStatus.PAST_DUE
        assert ActivityLog.objects.filter(
            type=ActivityType.PAYMENT_FAILED).exists()

    def test_deleted_cancels_subscription(self, api_client, active_sub):
        event = make_event("evt_7", "customer.subscription.deleted", {
            "id": "sub_123", "customer": "cus_123", "status": "canceled",
            "canceled_at": PERIOD_END, "cancel_at_period_end": False,
        })
        post_event(api_client, event)

        active_sub.refresh_from_db()
        assert active_sub.status == SubscriptionStatus.CANCELLED
        assert ActivityLog.objects.filter(
            type=ActivityType.SUBSCRIPTION_CANCELLED).exists()


class TestInvoiceEvents:
    def test_payment_failed_marks_past_due(self, api_client, active_sub):
        event = make_event("evt_8", "invoice.payment_failed", {
            "customer": "cus_123", "subscription": "sub_123",
        })
        post_event(api_client, event)

        active_sub.refresh_from_db()
        assert active_sub.status == SubscriptionStatus.PAST_DUE
        assert ActivityLog.objects.filter(
            type=ActivityType.PAYMENT_FAILED).exists()

    def test_payment_succeeded_recovers_past_due(self, api_client, client_user):
        sub = Subscription.objects.create(
            user=client_user,
            status=SubscriptionStatus.PAST_DUE,
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
        )
        event = make_event("evt_9", "invoice.payment_succeeded", {
            "customer": "cus_123", "subscription": "sub_123",
        })
        post_event(api_client, event)

        sub.refresh_from_db()
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_payment_succeeded_reads_new_invoice_shape(self, api_client, client_user):
        # Newer API versions nest the subscription id under parent
        sub = Subscription.objects.create(
            user=client_user,
            status=SubscriptionStatus.PAST_DUE,
            stripe_subscription_id="sub_nested",
        )
        event = make_event("evt_10", "invoice.payment_succeeded", {
            "customer": None,
            "parent": {"subscription_details": {"subscription": "sub_nested"}},
        })
        post_event(api_client, event)

        sub.refresh_from_db()
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_payment_succeeded_does_not_reactivate_cancelled(
        self, api_client, client_user,
    ):
        # A final invoice after cancellation must not resurrect the sub
        sub = Subscription.objects.create(
            user=client_user,
            status=SubscriptionStatus.CANCELLED,
            stripe_subscription_id="sub_123",
        )
        event = make_event("evt_11", "invoice.payment_succeeded", {
            "customer": None, "subscription": "sub_123",
        })
        post_event(api_client, event)

        sub.refresh_from_db()
        assert sub.status == SubscriptionStatus.CANCELLED
