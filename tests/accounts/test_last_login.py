"""Login should update User.last_login — simplejwt doesn't, we wired it ourselves."""
import pytest
from django.urls import reverse

LOGIN_URL = reverse("auth-login")


@pytest.mark.integration
class TestLastLoginTracking:
    def test_login_updates_last_login(self, db, api_client, client_user):
        assert client_user.last_login is None
        api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "TestPass123!"},
            format="json",
        )
        client_user.refresh_from_db()
        assert client_user.last_login is not None

    def test_failed_login_does_not_update_last_login(self, db, api_client, client_user):
        api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "WrongPass!"},
            format="json",
        )
        client_user.refresh_from_db()
        assert client_user.last_login is None
