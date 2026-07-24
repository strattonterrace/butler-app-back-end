"""Suspension/deletion side effects — the M2 wiring of accounts services.

Admin PATCH status changes must go through the services layer so the
login block, subscription cancel, and driver unassignment actually fire.
"""
import pytest

from apps.subscriptions.models import Subscription, SubscriptionStatus

from ..factories import ClientUserFactory, DriverUserFactory

pytestmark = pytest.mark.django_db


class TestAdminSuspendSideEffects:
    def _patch_status(self, auth_client, admin_user, target, new_status):
        return auth_client(admin_user).patch(
            f"/api/v1/users/{target.id}/",
            {"status": new_status},
            format="json",
        )

    def test_suspend_blocks_login_and_cancels_subscription(
        self, auth_client, admin_user,
    ):
        client = ClientUserFactory()
        Subscription.objects.create(
            user=client, status=SubscriptionStatus.ACTIVE,
        )
        resp = self._patch_status(auth_client, admin_user, client, "suspended")
        assert resp.status_code == 200

        client.refresh_from_db()
        assert client.status == "suspended"
        assert client.is_active is False  # JWT issuance blocked

        sub = Subscription.objects.get(user=client)
        assert sub.cancel_at_period_end is True

    def test_suspend_driver_unassigns_open_requests(
        self, auth_client, admin_user, client_user,
    ):
        from apps.requests.models import RequestStatus, ServiceRequest

        driver = DriverUserFactory()
        req = ServiceRequest.objects.create(
            client=client_user,
            driver=driver,
            status=RequestStatus.ASSIGNED,
            service_type="grocery",
            title="Groceries",
            description="Weekly run",
            pickup_location="Store",
            dropoff_location="Home",
        )
        resp = self._patch_status(auth_client, admin_user, driver, "suspended")
        assert resp.status_code == 200

        req.refresh_from_db()
        assert req.driver is None
        assert req.status == RequestStatus.REVIEWED

    def test_reactivate_restores_login(self, auth_client, admin_user):
        client = ClientUserFactory(status="suspended", is_active=False)
        resp = self._patch_status(auth_client, admin_user, client, "active")
        assert resp.status_code == 200

        client.refresh_from_db()
        assert client.status == "active"
        assert client.is_active is True


class TestAccountDeleteSideEffects:
    def test_self_delete_cancels_subscription(self, auth_client, client_user):
        Subscription.objects.create(
            user=client_user, status=SubscriptionStatus.ACTIVE,
        )
        resp = auth_client(client_user).delete(
            "/api/v1/users/me/", {"password": "TestPass123!"}, format="json",
        )
        assert resp.status_code == 204

        sub = Subscription.objects.get(user=client_user)
        assert sub.cancel_at_period_end is True
