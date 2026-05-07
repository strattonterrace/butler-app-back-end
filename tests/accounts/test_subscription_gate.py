"""IsActiveSubscriber gate — fail-closed enforcement.

Architecture invariant: every client gets a Subscription stub on register
(see apps.accounts.signals). Stripe webhooks (M2) flip status to 'active'.
"""
import pytest
from rest_framework.test import APIRequestFactory

from apps.accounts.permissions import IsActiveSubscriber
from apps.subscriptions.models import Subscription
from tests.factories import (
    AdminUserFactory, ClientUserFactory, DriverUserFactory, OperatorUserFactory,
)


@pytest.fixture
def rf():
    return APIRequestFactory()


# transactional_db fixture lets transaction.on_commit hooks fire — without
# transaction=True, pytest-django wraps each test in a savepoint that rolls
# back, so the signal's commit hook never runs.

@pytest.mark.integration
class TestIsActiveSubscriber:
    @pytest.mark.django_db(transaction=True)
    def test_register_auto_creates_inactive_subscription(self):
        client = ClientUserFactory()
        sub = Subscription.objects.get(user=client)
        assert sub.status == "inactive"
        assert sub.stripe_customer_id is None

    @pytest.mark.django_db(transaction=True)
    def test_inactive_subscription_blocks_client(self, rf):
        client = ClientUserFactory()  # inactive sub auto-created via on_commit
        request = rf.get("/")
        request.user = client
        assert IsActiveSubscriber().has_permission(request, view=None) is False

    @pytest.mark.django_db(transaction=True)
    def test_active_subscription_passes(self, rf):
        client = ClientUserFactory()
        sub = Subscription.objects.get(user=client)
        sub.status = "active"
        sub.save(update_fields=["status"])

        request = rf.get("/")
        request.user = client
        assert IsActiveSubscriber().has_permission(request, view=None) is True

    @pytest.mark.django_db(transaction=True)
    def test_past_due_blocks_client(self, rf):
        client = ClientUserFactory()
        sub = Subscription.objects.get(user=client)
        sub.status = "past_due"
        sub.save(update_fields=["status"])

        request = rf.get("/")
        request.user = client
        assert IsActiveSubscriber().has_permission(request, view=None) is False

    @pytest.mark.django_db(transaction=True)
    def test_cancelled_blocks_client(self, rf):
        client = ClientUserFactory()
        sub = Subscription.objects.get(user=client)
        sub.status = "cancelled"
        sub.save(update_fields=["status"])

        request = rf.get("/")
        request.user = client
        assert IsActiveSubscriber().has_permission(request, view=None) is False

    def test_operator_bypasses_gate(self, db, rf):
        request = rf.get("/")
        request.user = OperatorUserFactory()
        assert IsActiveSubscriber().has_permission(request, view=None) is True

    def test_driver_bypasses_gate(self, db, rf):
        request = rf.get("/")
        request.user = DriverUserFactory()
        assert IsActiveSubscriber().has_permission(request, view=None) is True

    def test_admin_bypasses_gate(self, db, rf):
        request = rf.get("/")
        request.user = AdminUserFactory()
        assert IsActiveSubscriber().has_permission(request, view=None) is True

    def test_anonymous_denied(self, db, rf):
        from django.contrib.auth.models import AnonymousUser
        request = rf.get("/")
        request.user = AnonymousUser()
        assert IsActiveSubscriber().has_permission(request, view=None) is False

    def test_client_with_no_subscription_row_denied(self, db, rf):
        """Defensive: if the registration signal somehow didn't fire, deny."""
        client = ClientUserFactory()
        Subscription.objects.filter(user=client).delete()
        request = rf.get("/")
        request.user = client
        assert IsActiveSubscriber().has_permission(request, view=None) is False
