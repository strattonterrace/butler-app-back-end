"""GET/PATCH /api/v1/users/me/ + admin user endpoints."""
import pytest
from django.urls import reverse

ME_URL = reverse("users-me")
LIST_URL = reverse("users-list")
CREATE_OPERATOR_URL = reverse("users-create-operator")


@pytest.mark.integration
class TestMe:
    def test_get_me_returns_current_user(self, db, auth_client, client_user):
        resp = auth_client(client_user).get(ME_URL)
        assert resp.status_code == 200
        assert resp.json()["email"] == client_user.email

    def test_patch_me_updates_allowed_fields(self, db, auth_client, client_user):
        resp = auth_client(client_user).patch(
            ME_URL, {"fullName": "New Name", "phone": "+1 555 0100"}, format="json",
        )
        assert resp.status_code == 200
        client_user.refresh_from_db()
        assert client_user.full_name == "New Name"
        assert client_user.phone == "+1 555 0100"

    @pytest.mark.edge_case
    def test_patch_me_cannot_change_role_or_email(self, db, auth_client, client_user):
        resp = auth_client(client_user).patch(
            ME_URL, {"role": "admin", "email": "hijack@example.com"}, format="json",
        )
        assert resp.status_code == 200  # Fields silently dropped (read-only)
        client_user.refresh_from_db()
        assert client_user.role == "client"
        assert client_user.email != "hijack@example.com"

    @pytest.mark.edge_case
    def test_get_me_requires_auth(self, db, api_client):
        resp = api_client.get(ME_URL)
        assert resp.status_code == 401


@pytest.mark.integration
class TestAdminUserEndpoints:
    def test_admin_can_list_users(self, db, auth_client, admin_user, client_user, driver_user):
        resp = auth_client(admin_user).get(LIST_URL)
        assert resp.status_code == 200
        # Pagination envelope: { status, data: { results, count, ... } }
        assert resp.json()["data"]["count"] >= 3

    def test_me_response_uses_camelcase(self, db, auth_client, client_user):
        # Sanity check: snake_case Python fields appear as camelCase on the wire
        resp = auth_client(client_user).get(ME_URL)
        body = resp.json()
        assert "fullName" in body
        assert "createdAt" in body
        assert "full_name" not in body
        assert "created_at" not in body

    def test_driver_user_payload_has_flat_vehicle_and_availability(
        self, db, auth_client, driver_user,
    ):
        from apps.drivers.models import DriverProfile
        DriverProfile.objects.create(
            user=driver_user,
            vehicle_make="Toyota", vehicle_model="Camry",
            vehicle_year=2022, license_plate="7ABC123",
            available_days=["monday", "tuesday"],
            available_hours="flexible",
            approval_status="approved",
        )
        resp = auth_client(driver_user).get(ME_URL)
        body = resp.json()
        assert body["vehicle"] == {
            "make": "Toyota", "model": "Camry", "year": 2022, "plate": "7ABC123",
        }
        assert body["availability"] == {
            "days": ["monday", "tuesday"], "hours": "flexible",
        }
        assert body["approvalStatus"] == "approved"

    def test_client_user_payload_omits_driver_fields(self, db, auth_client, client_user):
        resp = auth_client(client_user).get(ME_URL)
        body = resp.json()
        assert body["vehicle"] is None
        assert body["availability"] is None
        assert body["approvalStatus"] is None

    @pytest.mark.edge_case
    def test_non_admin_cannot_list_users(self, db, auth_client, client_user):
        resp = auth_client(client_user).get(LIST_URL)
        assert resp.status_code == 403

    def test_admin_can_create_operator(self, db, auth_client, admin_user):
        resp = auth_client(admin_user).post(
            CREATE_OPERATOR_URL,
            {
                "email": "newoperator@butler.com",
                "full_name": "New Operator",
                "password": "TempPass123!",
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "operator"

    @pytest.mark.edge_case
    def test_admin_cannot_self_suspend(self, db, auth_client, admin_user):
        url = reverse("users-detail", kwargs={"pk": admin_user.id})
        resp = auth_client(admin_user).patch(url, {"status": "suspended"}, format="json")
        assert resp.status_code == 400
        assert resp.json()["code"] == "ADMIN_CANNOT_SELF_SUSPEND"
