"""GET /api/v1/requests/stats/ — role-shaped dashboard counters (§10)."""
import pytest
from django.utils import timezone

from tests.factories import ClientUserFactory, ServiceRequestFactory, TerritoryFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/requests/stats/"


class TestStats:
    def test_client_shape(self, auth_client, territory_client):
        ServiceRequestFactory(client=territory_client, status="submitted")
        ServiceRequestFactory(client=territory_client, status="in_progress")
        ServiceRequestFactory(client=territory_client, status="completed")
        ServiceRequestFactory(client=territory_client, status="cancelled")
        ServiceRequestFactory()  # someone else's — must not count

        stats = auth_client(territory_client).get(URL).json()
        assert stats == {
            "total": 4, "active": 2, "completed": 1, "cancelled": 1,
        }

    def test_operator_shape(self, auth_client, territory_operator, territory_client, approved_driver):
        ServiceRequestFactory(client=territory_client, status="submitted")
        ServiceRequestFactory(client=territory_client, status="assigned", driver=approved_driver)
        ServiceRequestFactory(client=territory_client, status="in_progress", driver=approved_driver)
        ServiceRequestFactory(
            client=territory_client, status="completed",
            driver=approved_driver, completed_at=timezone.now(),
        )
        # Foreign-territory noise
        ServiceRequestFactory(client=ClientUserFactory(territory=TerritoryFactory()))

        stats = auth_client(territory_operator).get(URL).json()
        assert stats == {
            "pendingReview": 1, "assigned": 1, "inProgress": 1, "completedToday": 1,
        }

    def test_driver_shape(self, auth_client, territory_client, approved_driver):
        ServiceRequestFactory(client=territory_client, status="assigned", driver=approved_driver)
        ServiceRequestFactory(client=territory_client, status="in_progress", driver=approved_driver)
        ServiceRequestFactory(
            client=territory_client, status="completed",
            driver=approved_driver, completed_at=timezone.now(),
        )
        ServiceRequestFactory(client=territory_client)  # unassigned — invisible

        stats = auth_client(approved_driver).get(URL).json()
        assert stats == {
            "assigned": 1, "inProgress": 1, "completed": 1, "completedToday": 1,
        }

    def test_admin_shape(self, auth_client, admin_user, territory_client):
        ServiceRequestFactory(client=territory_client, status="submitted", service_type="grocery")
        ServiceRequestFactory(client=territory_client, status="completed", service_type="pharmacy")
        ServiceRequestFactory(status="submitted", service_type="grocery")

        stats = auth_client(admin_user).get(URL).json()
        assert stats["total"] == 3
        assert stats["todayCount"] == 3
        assert stats["byStatus"]["submitted"] == 2
        assert stats["byStatus"]["completed"] == 1
        assert stats["byStatus"]["cancelled"] == 0
        assert stats["byServiceType"] == {"grocery": 2, "pharmacy": 1}

    def test_anonymous_rejected(self, api_client, db):
        assert api_client.get(URL).status_code == 401
