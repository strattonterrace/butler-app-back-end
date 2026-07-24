"""Admin analytics + user-action endpoints (§12)."""
import pytest
from django.utils import timezone

from apps.activity.services import ActivityType, emit
from apps.subscriptions.models import Subscription, SubscriptionStatus, WebhookEvent
from tests.factories import (
    AdminUserFactory,
    ClientUserFactory,
    DriverProfileFactory,
    OperatorUserFactory,
    ServiceRequestFactory,
    TerritoryFactory,
)

pytestmark = pytest.mark.django_db

METRICS = "/api/v1/admin/metrics/"
REVENUE = "/api/v1/admin/revenue/"
ACTIVITY = "/api/v1/admin/activity/"


def _active_sub(user):
    Subscription.objects.update_or_create(
        user=user, defaults={"status": SubscriptionStatus.ACTIVE},
    )


class TestMetrics:
    def test_metrics_shape_and_counts(self, auth_client):
        admin = AdminUserFactory()
        c1, c2 = ClientUserFactory(), ClientUserFactory()
        _active_sub(c1)
        _active_sub(c2)
        DriverProfileFactory(approval_status="approved")
        DriverProfileFactory(approval_status="pending")
        ServiceRequestFactory(client=c1, status="submitted")
        ServiceRequestFactory(
            client=c2, status="completed", completed_at=timezone.now(),
        )
        # Two paid invoices in the ledger → total_revenue = 2 * 199
        WebhookEvent.objects.create(stripe_event_id="e1", event_type="invoice.payment_succeeded")
        WebhookEvent.objects.create(stripe_event_id="e2", event_type="invoice.payment_succeeded")

        data = auth_client(admin).get(METRICS).json()
        assert data["totalClients"] == 2
        assert data["activeSubscribers"] == 2
        assert data["totalDrivers"] == 2
        assert data["approvedDrivers"] == 1
        assert data["pendingDriverApplications"] == 1
        assert data["totalRequests"] == 2
        assert data["activeRequests"] == 1
        assert data["completedRequestsToday"] == 1
        assert float(data["monthlyRevenue"]) == 398.0
        assert float(data["totalRevenue"]) == 398.0
        assert data["churnRate"] == 0.0

    def test_churn_rate_computed(self, auth_client):
        admin = AdminUserFactory()
        active = ClientUserFactory()
        _active_sub(active)
        churned = ClientUserFactory()
        Subscription.objects.update_or_create(
            user=churned,
            defaults={
                "status": SubscriptionStatus.CANCELLED,
                "cancelled_at": timezone.now(),
            },
        )
        data = auth_client(admin).get(METRICS).json()
        # 1 churned / (1 active + 1 churned) = 0.5
        assert data["churnRate"] == 0.5

    def test_empty_platform_no_nan(self, auth_client):
        data = auth_client(AdminUserFactory()).get(METRICS).json()
        assert data["churnRate"] == 0.0
        assert float(data["monthlyRevenue"]) == 0.0

    def test_non_admin_forbidden(self, auth_client):
        assert auth_client(OperatorUserFactory()).get(METRICS).status_code == 403
        assert auth_client(ClientUserFactory()).get(METRICS).status_code == 403

    def test_anonymous_rejected(self, api_client):
        assert api_client.get(METRICS).status_code == 401


class TestRevenue:
    def test_revenue_series_and_summary(self, auth_client):
        admin = AdminUserFactory()
        c = ClientUserFactory()
        _active_sub(c)
        WebhookEvent.objects.create(stripe_event_id="e1", event_type="invoice.payment_succeeded")

        data = auth_client(admin).get(REVENUE).json()
        assert len(data["monthly"]) == 6
        # months ascending, YYYY-MM
        months = [m["month"] for m in data["monthly"]]
        assert months == sorted(months)
        assert data["summary"]["activeSubscribers"] == 1
        assert float(data["summary"]["totalRevenue"]) == 199.0
        assert float(data["summary"]["averageRevenuePerUser"]) == 199.0

    def test_non_admin_forbidden(self, auth_client):
        assert auth_client(ClientUserFactory()).get(REVENUE).status_code == 403


class TestActivityFeed:
    def test_returns_recent_events_newest_first(self, auth_client):
        admin = AdminUserFactory()
        for i in range(3):
            emit(ActivityType.ORDER_SUBMITTED, message=f"event {i}", actor=admin)

        data = auth_client(admin).get(ACTIVITY).json()
        assert len(data) == 3
        assert data[0]["message"] == "event 2"  # newest first
        assert data[0]["actor"]["role"] == "admin"

    def test_limit_param_caps_results(self, auth_client):
        admin = AdminUserFactory()
        for i in range(5):
            emit(ActivityType.ORDER_SUBMITTED, message=f"e{i}")
        data = auth_client(admin).get(ACTIVITY, {"limit": 2}).json()
        assert len(data) == 2

    def test_default_limit_is_20(self, auth_client):
        admin = AdminUserFactory()
        for i in range(25):
            emit(ActivityType.ORDER_SUBMITTED, message=f"e{i}")
        data = auth_client(admin).get(ACTIVITY).json()
        assert len(data) == 20

    def test_non_admin_forbidden(self, auth_client):
        assert auth_client(OperatorUserFactory()).get(ACTIVITY).status_code == 403


class TestSuspendReactivate:
    def suspend_url(self, user):
        return f"/api/v1/admin/users/{user.id}/suspend/"

    def reactivate_url(self, user):
        return f"/api/v1/admin/users/{user.id}/reactivate/"

    def test_admin_suspends_client(self, auth_client):
        admin = AdminUserFactory()
        client = ClientUserFactory()
        resp = auth_client(admin).post(self.suspend_url(client))
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"
        client.refresh_from_db()
        assert client.status == "suspended"
        assert client.is_active is False

    def test_suspend_driver_unassigns_open_requests(self, auth_client):
        admin = AdminUserFactory()
        territory = TerritoryFactory()
        profile = DriverProfileFactory(territory=territory)
        client = ClientUserFactory(territory=territory)
        sr = ServiceRequestFactory(
            client=client, status="assigned", driver=profile.user,
        )
        auth_client(admin).post(self.suspend_url(profile.user))
        sr.refresh_from_db()
        assert sr.driver is None
        assert sr.status == "reviewed"

    def test_admin_cannot_self_suspend(self, auth_client):
        admin = AdminUserFactory()
        resp = auth_client(admin).post(self.suspend_url(admin))
        assert resp.status_code == 400
        assert resp.json()["code"] == "ADMIN_CANNOT_SELF_SUSPEND"

    def test_reactivate_restores_account(self, auth_client):
        admin = AdminUserFactory()
        client = ClientUserFactory(status="suspended", is_active=False)
        resp = auth_client(admin).post(self.reactivate_url(client))
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        client.refresh_from_db()
        assert client.status == "active"
        assert client.is_active is True

    def test_non_admin_cannot_suspend(self, auth_client):
        client = ClientUserFactory()
        assert auth_client(OperatorUserFactory()).post(self.suspend_url(client)).status_code == 403

    def test_suspend_unknown_user_404(self, auth_client):
        url = "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/suspend/"
        assert auth_client(AdminUserFactory()).post(url).status_code == 404
