"""POST /api/v1/auth/password-change/ — logged-in change."""
import pytest
from django.urls import reverse

URL = reverse("auth-password-change")
LOGIN_URL = reverse("auth-login")


@pytest.mark.integration
class TestPasswordChange:
    def test_changes_password_with_correct_current(self, db, auth_client, client_user):
        resp = auth_client(client_user).post(
            URL,
            {
                "currentPassword": "TestPass123!",
                "newPassword": "BrandNewPass123!",
                "confirmPassword": "BrandNewPass123!",
            },
            format="json",
        )
        assert resp.status_code == 200
        client_user.refresh_from_db()
        assert client_user.check_password("BrandNewPass123!") is True

    @pytest.mark.edge_case
    def test_rejects_wrong_current_password(self, db, auth_client, client_user):
        resp = auth_client(client_user).post(
            URL,
            {
                "currentPassword": "WrongPass!",
                "newPassword": "BrandNewPass123!",
                "confirmPassword": "BrandNewPass123!",
            },
            format="json",
        )
        assert resp.status_code == 400
        client_user.refresh_from_db()
        assert client_user.check_password("TestPass123!") is True  # unchanged

    @pytest.mark.edge_case
    def test_rejects_mismatched_new_passwords(self, db, auth_client, client_user):
        resp = auth_client(client_user).post(
            URL,
            {
                "currentPassword": "TestPass123!",
                "newPassword": "OnePass123!",
                "confirmPassword": "DifferentPass123!",
            },
            format="json",
        )
        assert resp.status_code == 400

    @pytest.mark.edge_case
    def test_requires_authentication(self, db, api_client):
        resp = api_client.post(
            URL,
            {
                "currentPassword": "x",
                "newPassword": "BrandNewPass123!",
                "confirmPassword": "BrandNewPass123!",
            },
            format="json",
        )
        assert resp.status_code == 401
