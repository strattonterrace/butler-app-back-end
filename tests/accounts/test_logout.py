"""POST /api/v1/auth/logout/ — refresh token blacklist."""
import pytest
from django.urls import reverse

LOGIN_URL = reverse("auth-login")
LOGOUT_URL = reverse("auth-logout")
REFRESH_URL = reverse("auth-token-refresh")


@pytest.mark.integration
class TestLogout:
    def test_logout_blacklists_refresh_token(self, db, api_client, client_user):
        login = api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "TestPass123!"},
            format="json",
        )
        access = login.json()["access"]
        refresh = login.json()["refresh"]

        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = api_client.post(LOGOUT_URL, {"refresh": refresh}, format="json")
        assert resp.status_code == 204

        # The blacklisted token should now fail on refresh
        api_client.credentials()  # clear auth
        refresh_resp = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        assert refresh_resp.status_code == 401

    @pytest.mark.edge_case
    def test_logout_requires_auth(self, db, api_client):
        resp = api_client.post(LOGOUT_URL, {"refresh": "x"}, format="json")
        assert resp.status_code == 401
