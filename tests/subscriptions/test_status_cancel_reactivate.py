"""Status, cancel, and reactivate endpoints."""
from unittest.mock import patch

import pytest

from apps.subscriptions.models import Subscription, SubscriptionStatus

pytestmark = pytest.mark.django_db

STATUS_URL = "/api/v1/subscriptions/status/"
CANCEL_URL = "/api/v1/subscriptions/cancel/"
REACTIVATE_URL = "/api/v1/subscriptions/reactivate/"


class TestSubscriptionStatus:
    def test_returns_default_inactive_state(self, auth_client, client_user):
        resp = auth_client(client_user).get(STATUS_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "inactive"
        assert body["planAmount"] == "199.00"
        assert body["cancelAtPeriodEnd"] is False

    def test_non_client_roles_denied(self, auth_client, operator_user, admin_user):
        assert auth_client(operator_user).get(STATUS_URL).status_code == 403
        assert auth_client(admin_user).get(STATUS_URL).status_code == 403

    def test_requires_authentication(self, api_client):
        assert api_client.get(STATUS_URL).status_code == 401


class TestCancelSubscription:
    def test_cancels_active_subscription_on_stripe(
        self, auth_client, client_user, settings,
    ):
        settings.STRIPE_SECRET_KEY = "sk_test_x"
        Subscription.objects.create(
            user=client_user,
            status=SubscriptionStatus.ACTIVE,
            stripe_subscription_id="sub_123",
        )
        with patch("stripe.Subscription.modify") as modify:
            resp = auth_client(client_user).post(CANCEL_URL)

        assert resp.status_code == 200
        body = resp.json()
        assert body["cancelAtPeriodEnd"] is True
        assert body["cancelledAt"] is not None
        # Status stays active until the period actually ends
        assert body["status"] == "active"
        modify.assert_called_once_with("sub_123", cancel_at_period_end=True)

    def test_cancels_local_only_subscription_without_stripe(
        self, auth_client, client_user,
    ):
        # Comped/manual subscription with no Stripe id — cancel is local-only
        Subscription.objects.create(
            user=client_user, status=SubscriptionStatus.ACTIVE,
        )
        with patch("stripe.Subscription.modify") as modify:
            resp = auth_client(client_user).post(CANCEL_URL)

        assert resp.status_code == 200
        assert resp.json()["cancelAtPeriodEnd"] is True
        modify.assert_not_called()

    def test_cancel_without_active_subscription_fails(self, auth_client, client_user):
        resp = auth_client(client_user).post(CANCEL_URL)
        assert resp.status_code == 400

    def test_requires_client_role(self, auth_client, operator_user):
        assert auth_client(operator_user).post(CANCEL_URL).status_code == 403


class TestReactivateSubscription:
    def test_reactivates_pending_cancellation(
        self, auth_client, client_user, settings,
    ):
        from django.utils import timezone

        settings.STRIPE_SECRET_KEY = "sk_test_x"
        Subscription.objects.create(
            user=client_user,
            status=SubscriptionStatus.ACTIVE,
            stripe_subscription_id="sub_123",
            cancel_at_period_end=True,
            cancelled_at=timezone.now(),
        )
        with patch("stripe.Subscription.modify") as modify:
            resp = auth_client(client_user).post(REACTIVATE_URL)

        assert resp.status_code == 200
        body = resp.json()
        assert body["cancelAtPeriodEnd"] is False
        assert body["cancelledAt"] is None
        modify.assert_called_once_with("sub_123", cancel_at_period_end=False)

    def test_reactivate_without_pending_cancel_fails(self, auth_client, client_user):
        Subscription.objects.create(
            user=client_user, status=SubscriptionStatus.ACTIVE,
        )
        resp = auth_client(client_user).post(REACTIVATE_URL)
        assert resp.status_code == 400
