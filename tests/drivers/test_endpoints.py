"""Driver endpoints — apply, status, available, pending, approve, reject (§11)."""
import pytest

from apps.activity.models import ActivityLog
from apps.drivers.models import DriverProfile
from tests.factories import (
    AdminUserFactory,
    ClientUserFactory,
    DriverProfileFactory,
    OperatorUserFactory,
    ServiceRequestFactory,
    TerritoryFactory,
)

pytestmark = pytest.mark.django_db

APPLY = "/api/v1/drivers/apply/"
STATUS = "/api/v1/drivers/application-status/"
AVAILABLE = "/api/v1/drivers/available/"
PENDING = "/api/v1/drivers/pending/"

VALID_APPLICATION = {
    "phone": "+1 (949) 555-0101",
    "vehicle_make": "Toyota",
    "vehicle_model": "Camry",
    "vehicle_year": 2022,
    "license_plate": "7ABC123",
    "available_days": ["monday", "tuesday", "wednesday"],
    "available_hours": "flexible",
}


class TestApply:
    def test_client_applies_and_becomes_pending_driver(self, auth_client, client_user):
        resp = auth_client(client_user).post(APPLY, VALID_APPLICATION, format="json")

        assert resp.status_code == 201
        assert resp.json()["approvalStatus"] == "pending"

        client_user.refresh_from_db()
        assert client_user.role == "driver"
        assert client_user.phone == "+1 (949) 555-0101"
        profile = DriverProfile.objects.get(user=client_user)
        assert profile.approval_status == "pending"
        assert profile.vehicle_make == "Toyota"

    def test_apply_emits_activity(self, auth_client, client_user):
        auth_client(client_user).post(APPLY, VALID_APPLICATION, format="json")
        assert ActivityLog.objects.filter(type="driver_application").exists()

    def test_existing_driver_cannot_reapply(self, auth_client, db):
        driver = DriverProfileFactory().user
        resp = auth_client(driver).post(APPLY, VALID_APPLICATION, format="json")
        assert resp.status_code == 400
        assert resp.json()["code"] == "DRV_ALREADY_APPLIED"

    def test_anonymous_cannot_apply(self, api_client, db):
        assert api_client.post(APPLY, VALID_APPLICATION, format="json").status_code == 401

    def test_missing_vehicle_fields_rejected(self, auth_client, client_user):
        resp = auth_client(client_user).post(
            APPLY, {"available_days": ["monday"]}, format="json",
        )
        assert resp.status_code == 400
        errors = resp.json()["errors"]
        assert "vehicleMake" in errors and "licensePlate" in errors

    def test_empty_available_days_rejected(self, auth_client, client_user):
        body = {**VALID_APPLICATION, "available_days": []}
        resp = auth_client(client_user).post(APPLY, body, format="json")
        assert resp.status_code == 400


class TestApplicationStatus:
    def test_driver_reads_own_status(self, auth_client, db):
        profile = DriverProfileFactory(approval_status="pending")
        resp = auth_client(profile.user).get(STATUS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["approvalStatus"] == "pending"
        assert "appliedAt" in data

    def test_non_driver_forbidden(self, auth_client, client_user):
        assert auth_client(client_user).get(STATUS).status_code == 403


class TestAvailableDrivers:
    def test_operator_sees_approved_in_territory_least_busy_first(
        self, auth_client, db,
    ):
        territory = TerritoryFactory()
        operator = OperatorUserFactory(territory=territory)
        busy = DriverProfileFactory(territory=territory)
        free = DriverProfileFactory(territory=territory)
        # Give `busy` an active assignment
        client = ClientUserFactory(territory=territory)
        ServiceRequestFactory(client=client, status="assigned", driver=busy.user)

        resp = auth_client(operator).get(AVAILABLE)
        assert resp.status_code == 200
        rows = resp.json()
        ids = [r["id"] for r in rows]
        # Least busy first
        assert ids[0] == str(free.user.id)
        assert ids[1] == str(busy.user.id)
        busy_row = next(r for r in rows if r["id"] == str(busy.user.id))
        assert busy_row["currentTaskCount"] == 1

    def test_operator_excludes_other_territory(self, auth_client, db):
        territory = TerritoryFactory()
        operator = OperatorUserFactory(territory=territory)
        DriverProfileFactory(territory=territory)
        DriverProfileFactory(territory=TerritoryFactory())  # elsewhere

        rows = auth_client(operator).get(AVAILABLE).json()
        assert len(rows) == 1

    def test_available_excludes_pending_and_rejected(self, auth_client, db):
        territory = TerritoryFactory()
        operator = OperatorUserFactory(territory=territory)
        DriverProfileFactory(territory=territory, approval_status="approved")
        DriverProfileFactory(territory=territory, approval_status="pending")
        DriverProfileFactory(territory=territory, approval_status="rejected")

        rows = auth_client(operator).get(AVAILABLE).json()
        assert len(rows) == 1

    def test_admin_sees_all_approved(self, auth_client, db):
        DriverProfileFactory(territory=TerritoryFactory())
        DriverProfileFactory(territory=TerritoryFactory())
        rows = auth_client(AdminUserFactory()).get(AVAILABLE).json()
        assert len(rows) == 2

    def test_client_forbidden(self, auth_client, client_user):
        assert auth_client(client_user).get(AVAILABLE).status_code == 403


class TestPending:
    def test_admin_sees_pending_only(self, auth_client, db):
        DriverProfileFactory(approval_status="pending")
        DriverProfileFactory(approval_status="approved")
        rows = auth_client(AdminUserFactory()).get(PENDING).json()
        assert len(rows) == 1
        assert rows[0]["approvalStatus"] == "pending"

    def test_operator_forbidden(self, auth_client, db):
        assert auth_client(OperatorUserFactory()).get(PENDING).status_code == 403


class TestApproveReject:
    def approve_url(self, driver_user):
        return f"/api/v1/drivers/{driver_user.id}/approve/"

    def reject_url(self, driver_user):
        return f"/api/v1/drivers/{driver_user.id}/reject/"

    def test_admin_approves(self, auth_client, db):
        admin = AdminUserFactory()
        profile = DriverProfileFactory(approval_status="pending")

        resp = auth_client(admin).post(self.approve_url(profile.user))
        assert resp.status_code == 200
        assert resp.json()["approvalStatus"] == "approved"

        profile.refresh_from_db()
        assert profile.approval_status == "approved"
        assert profile.approved_by == admin
        assert profile.approved_at is not None
        assert ActivityLog.objects.filter(type="driver_approved").exists()

    def test_double_approve_rejected(self, auth_client, db):
        admin = AdminUserFactory()
        profile = DriverProfileFactory(approval_status="approved")
        resp = auth_client(admin).post(self.approve_url(profile.user))
        assert resp.status_code == 400
        assert resp.json()["code"] == "DRV_ALREADY_APPROVED"

    def test_admin_rejects_with_reason(self, auth_client, db):
        admin = AdminUserFactory()
        profile = DriverProfileFactory(approval_status="pending")

        resp = auth_client(admin).post(
            self.reject_url(profile.user),
            {"reason": "Incomplete vehicle information"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["approvalStatus"] == "rejected"

        profile.refresh_from_db()
        assert profile.approval_status == "rejected"
        assert profile.rejection_reason == "Incomplete vehicle information"
        assert profile.rejected_at is not None
        assert ActivityLog.objects.filter(type="driver_rejected").exists()

    def test_operator_cannot_approve(self, auth_client, db):
        profile = DriverProfileFactory(approval_status="pending")
        resp = auth_client(OperatorUserFactory()).post(self.approve_url(profile.user))
        assert resp.status_code == 403

    def test_approve_unknown_driver_404(self, auth_client, db):
        url = "/api/v1/drivers/00000000-0000-0000-0000-000000000000/approve/"
        assert auth_client(AdminUserFactory()).post(url).status_code == 404

    def test_approved_driver_can_now_be_assigned(self, auth_client, db):
        """End-to-end: approval unlocks assignment eligibility."""
        admin = AdminUserFactory()
        territory = TerritoryFactory()
        profile = DriverProfileFactory(territory=territory, approval_status="pending")
        auth_client(admin).post(self.approve_url(profile.user))

        # Now assignable in the available list
        operator = OperatorUserFactory(territory=territory)
        rows = auth_client(operator).get(AVAILABLE).json()
        assert str(profile.user.id) in [r["id"] for r in rows]
