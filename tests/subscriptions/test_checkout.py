"""Checkout session endpoint — POST /api/v1/subscriptions/create-checkout/."""
from unittest.mock import patch

import pytest

from apps.subscriptions.models import Subscription, SubscriptionStatus

pytestmark = pytest.mark.django_db

URL = "/api/v1/subscriptions/create-checkout/"


@pytest.fixture
def stripe_settings(settings):
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_PRICE_ID = "price_x"
    settings.FRONTEND_URL = "http://testserver-frontend"
    return settings


class TestCreateCheckout:
    def test_returns_checkout_url_and_creates_customer(
        self, auth_client, client_user, stripe_settings,
    ):
        with patch("stripe.Customer.create") as customer_create, \
             patch("stripe.checkout.Session.create") as session_create:
            customer_create.return_value = {"id": "cus_123"}
            session_create.return_value = {"url": "https://checkout.stripe.com/c/pay/test"}

            resp = auth_client(client_user).post(URL)

        assert resp.status_code == 200
        assert resp.json()["checkoutUrl"] == "https://checkout.stripe.com/c/pay/test"

        sub = Subscription.objects.get(user=client_user)
        assert sub.stripe_customer_id == "cus_123"

        _, kwargs = session_create.call_args
        assert kwargs["mode"] == "subscription"
        assert kwargs["customer"] == "cus_123"
        assert kwargs["line_items"] == [{"price": "price_x", "quantity": 1}]
        assert kwargs["client_reference_id"] == str(client_user.id)
        assert kwargs["success_url"].startswith("http://testserver-frontend/dashboard")
        assert kwargs["cancel_url"].startswith("http://testserver-frontend/subscribe")

    def test_reuses_existing_stripe_customer(
        self, auth_client, client_user, stripe_settings,
    ):
        Subscription.objects.create(
            user=client_user,
            status=SubscriptionStatus.INACTIVE,
            stripe_customer_id="cus_existing",
        )
        with patch("stripe.Customer.create") as customer_create, \
             patch("stripe.checkout.Session.create") as session_create:
            session_create.return_value = {"url": "https://checkout.stripe.com/x"}
            resp = auth_client(client_user).post(URL)

        assert resp.status_code == 200
        customer_create.assert_not_called()

    def test_conflict_when_already_active(
        self, auth_client, client_user, stripe_settings,
    ):
        Subscription.objects.create(
            user=client_user, status=SubscriptionStatus.ACTIVE,
        )
        resp = auth_client(client_user).post(URL)
        assert resp.status_code == 409
        assert resp.json()["code"] == "SUB_ALREADY_ACTIVE"

    def test_requires_client_role(self, auth_client, driver_user, stripe_settings):
        resp = auth_client(driver_user).post(URL)
        assert resp.status_code == 403

    def test_requires_authentication(self, api_client):
        resp = api_client.post(URL)
        assert resp.status_code == 401

    def test_stripe_not_configured_returns_502(
        self, auth_client, client_user, settings,
    ):
        settings.STRIPE_SECRET_KEY = ""
        resp = auth_client(client_user).post(URL)
        assert resp.status_code == 502
        assert resp.json()["code"] == "PAYMENT_SERVICE_ERROR"
