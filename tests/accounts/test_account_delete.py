"""DELETE /api/v1/users/me/ — soft delete with password confirmation."""
import pytest
from django.urls import reverse

URL = reverse("users-me")


@pytest.mark.integration
class TestAccountDelete:
    def test_deletes_account_with_correct_password(self, db, auth_client, client_user):
        resp = auth_client(client_user).delete(
            URL, {"password": "TestPass123!"}, format="json",
        )
        assert resp.status_code == 204
        client_user.refresh_from_db()
        # Soft-delete: row still exists but flagged inactive + suspended
        assert client_user.status == "suspended"
        assert client_user.is_active is False

    @pytest.mark.edge_case
    def test_rejects_wrong_password(self, db, auth_client, client_user):
        resp = auth_client(client_user).delete(
            URL, {"password": "WrongPass!"}, format="json",
        )
        assert resp.status_code == 400
        client_user.refresh_from_db()
        assert client_user.status == "active"
        assert client_user.is_active is True

    @pytest.mark.edge_case
    def test_requires_authentication(self, db, api_client):
        resp = api_client.delete(URL, {"password": "x"}, format="json")
        assert resp.status_code == 401
