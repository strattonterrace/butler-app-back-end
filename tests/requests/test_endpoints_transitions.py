"""PATCH /api/v1/requests/:id/status/ — the §10 transition matrix, end to end."""
import pytest

from apps.activity.models import ActivityLog
from apps.requests.models import ServiceRequest, StatusHistory
from tests.factories import (
    ClientUserFactory,
    DriverProfileFactory,
    DriverUserFactory,
    ServiceRequestFactory,
    TerritoryFactory,
)

pytestmark = pytest.mark.django_db


def status_url(sr):
    return f"/api/v1/requests/{sr.id}/status/"


@pytest.fixture
def sr(territory_client):
    return ServiceRequestFactory(client=territory_client)


class TestHappyPath:
    def test_full_lifecycle(
        self, auth_client, sr, territory_operator, approved_driver, admin_user,
    ):
        op = auth_client(territory_operator)
        drv = auth_client(approved_driver)
        adm = auth_client(admin_user)

        # submitted → reviewed (operator)
        resp = op.patch(status_url(sr), {"status": "reviewed"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reviewed"
        assert resp.json()["operator"]["id"] == str(territory_operator.id)

        # reviewed → assigned (operator, needs driver_id)
        resp = op.patch(
            status_url(sr),
            {"status": "assigned", "driver_id": str(approved_driver.id)},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "assigned"
        assert data["driver"]["id"] == str(approved_driver.id)
        assert data["assignedAt"] is not None

        # assigned → in_progress (assigned driver)
        resp = drv.patch(status_url(sr), {"status": "in_progress"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["startedAt"] is not None

        # in_progress → completed (assigned driver, notes stored)
        resp = drv.patch(
            status_url(sr),
            {"status": "completed", "completion_notes": "Left at the door"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["completedAt"] is not None
        assert resp.json()["completionNotes"] == "Left at the door"

        # completed → closed (admin)
        resp = adm.patch(status_url(sr), {"status": "closed"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["closedAt"] is not None

        # Full audit trail: 5 transitions (factory-created row has no opening
        # entry — creation history is covered in the create-endpoint tests)
        assert StatusHistory.objects.filter(request=sr).count() == 5

        # Activity events fired for the visible lifecycle moments
        types = set(
            ActivityLog.objects.filter(target_request=sr).values_list("type", flat=True)
        )
        assert {"order_assigned", "order_pickup", "order_completed"} <= types

    def test_admin_can_run_operator_transitions(self, auth_client, sr, admin_user, approved_driver):
        adm = auth_client(admin_user)
        assert adm.patch(status_url(sr), {"status": "reviewed"}, format="json").status_code == 200
        resp = adm.patch(
            status_url(sr),
            {"status": "assigned", "driver_id": str(approved_driver.id)},
            format="json",
        )
        assert resp.status_code == 200


class TestInvalidTransitions:
    def test_skipping_a_step_conflicts(self, auth_client, sr, territory_operator):
        resp = auth_client(territory_operator).patch(
            status_url(sr), {"status": "in_progress"}, format="json",
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "REQ_INVALID_TRANSITION"

    def test_same_status_conflicts(self, auth_client, sr, territory_operator):
        resp = auth_client(territory_operator).patch(
            status_url(sr), {"status": "submitted"}, format="json",
        )
        assert resp.status_code == 409

    def test_cancelled_request_is_terminal(self, auth_client, territory_client, territory_operator):
        sr = ServiceRequestFactory(client=territory_client, status="cancelled")
        resp = auth_client(territory_operator).patch(
            status_url(sr), {"status": "reviewed"}, format="json",
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "REQ_ALREADY_CANCELLED"

    def test_closed_request_is_terminal(self, auth_client, territory_client, territory_operator):
        sr = ServiceRequestFactory(client=territory_client, status="closed")
        resp = auth_client(territory_operator).patch(
            status_url(sr),
            {"status": "cancelled", "cancel_reason": "too late"},
            format="json",
        )
        assert resp.status_code == 409

    def test_unknown_status_rejected(self, auth_client, sr, territory_operator):
        resp = auth_client(territory_operator).patch(
            status_url(sr), {"status": "teleported"}, format="json",
        )
        assert resp.status_code == 400


class TestRoleEnforcement:
    def test_client_cannot_review(self, auth_client, sr, territory_client):
        resp = auth_client(territory_client).patch(
            status_url(sr), {"status": "reviewed"}, format="json",
        )
        assert resp.status_code == 403

    def test_unassigned_driver_cannot_start(
        self, auth_client, territory_client, territory_operator, approved_driver, territory,
    ):
        sr = ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        other_driver = DriverProfileFactory(territory=territory).user
        # other_driver isn't assigned — and can't even see the request → 404
        resp = auth_client(other_driver).patch(
            status_url(sr), {"status": "in_progress"}, format="json",
        )
        assert resp.status_code == 404

    def test_operator_cannot_start_progress(
        self, auth_client, territory_client, territory_operator, approved_driver,
    ):
        sr = ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        resp = auth_client(territory_operator).patch(
            status_url(sr), {"status": "in_progress"}, format="json",
        )
        assert resp.status_code == 403

    def test_other_clients_request_is_invisible(self, auth_client, sr, db):
        stranger = ClientUserFactory()
        resp = auth_client(stranger).patch(
            status_url(sr),
            {"status": "cancelled", "cancel_reason": "not mine"},
            format="json",
        )
        assert resp.status_code == 404


class TestAssignment:
    def test_assign_requires_driver_id(self, auth_client, territory_client, territory_operator):
        sr = ServiceRequestFactory(client=territory_client, status="reviewed")
        resp = auth_client(territory_operator).patch(
            status_url(sr), {"status": "assigned"}, format="json",
        )
        assert resp.status_code == 400
        assert "driverId" in resp.json()["errors"]

    def test_assign_unapproved_driver_rejected(
        self, auth_client, territory_client, territory_operator, territory,
    ):
        pending = DriverProfileFactory(territory=territory, approval_status="pending").user
        sr = ServiceRequestFactory(client=territory_client, status="reviewed")
        resp = auth_client(territory_operator).patch(
            status_url(sr),
            {"status": "assigned", "driver_id": str(pending.id)},
            format="json",
        )
        assert resp.status_code == 400

    def test_assign_cross_territory_driver_rejected(
        self, auth_client, territory_client, territory_operator,
    ):
        foreign_driver = DriverProfileFactory(territory=TerritoryFactory()).user
        sr = ServiceRequestFactory(client=territory_client, status="reviewed")
        resp = auth_client(territory_operator).patch(
            status_url(sr),
            {"status": "assigned", "driver_id": str(foreign_driver.id)},
            format="json",
        )
        assert resp.status_code == 400

    def test_assign_nonexistent_driver_rejected(
        self, auth_client, territory_client, territory_operator,
    ):
        sr = ServiceRequestFactory(client=territory_client, status="reviewed")
        resp = auth_client(territory_operator).patch(
            status_url(sr),
            {"status": "assigned", "driver_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert resp.status_code == 400

    def test_assign_user_without_profile_rejected(
        self, auth_client, territory_client, territory_operator,
    ):
        bare_driver = DriverUserFactory()  # no DriverProfile at all
        sr = ServiceRequestFactory(client=territory_client, status="reviewed")
        resp = auth_client(territory_operator).patch(
            status_url(sr),
            {"status": "assigned", "driver_id": str(bare_driver.id)},
            format="json",
        )
        assert resp.status_code == 400


class TestCancellation:
    def test_client_cancels_own_submitted_request(self, auth_client, sr, territory_client):
        resp = auth_client(territory_client).patch(
            status_url(sr),
            {"status": "cancelled", "cancel_reason": "Changed my mind"},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancelReason"] == "Changed my mind"
        assert data["cancelledAt"] is not None

    def test_cancel_requires_reason(self, auth_client, sr, territory_client):
        resp = auth_client(territory_client).patch(
            status_url(sr), {"status": "cancelled"}, format="json",
        )
        assert resp.status_code == 400
        assert "cancelReason" in resp.json()["errors"]

    def test_client_cannot_cancel_after_assignment(
        self, auth_client, territory_client, approved_driver,
    ):
        sr = ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        resp = auth_client(territory_client).patch(
            status_url(sr),
            {"status": "cancelled", "cancel_reason": "too slow"},
            format="json",
        )
        assert resp.status_code == 409

    def test_operator_can_cancel_in_progress(
        self, auth_client, territory_client, territory_operator, approved_driver,
    ):
        sr = ServiceRequestFactory(
            client=territory_client, status="in_progress", driver=approved_driver,
        )
        resp = auth_client(territory_operator).patch(
            status_url(sr),
            {"status": "cancelled", "cancel_reason": "Store closed"},
            format="json",
        )
        assert resp.status_code == 200
        assert ActivityLog.objects.filter(
            type="order_cancelled", target_request=sr,
        ).exists()
