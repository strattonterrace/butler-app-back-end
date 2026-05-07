"""POST /api/v1/auth/login/ — JWT pair + role embedding + suspension check."""
import pytest
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

LOGIN_URL = reverse("auth-login")
REFRESH_URL = reverse("auth-token-refresh")


@pytest.mark.integration
class TestLogin:
    def test_login_with_valid_credentials_returns_tokens_and_user(self, db, api_client, client_user):
        resp = api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "TestPass123!"},
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access" in body and "refresh" in body
        assert body["user"]["id"] == str(client_user.id)
        assert body["user"]["role"] == "client"

    def test_jwt_embeds_role_claim(self, db, api_client, operator_user):
        resp = api_client.post(
            LOGIN_URL,
            {"email": operator_user.email, "password": "TestPass123!"},
            format="json",
        )
        token = AccessToken(resp.json()["access"])
        assert token["role"] == "operator"
        assert token["email"] == operator_user.email

    @pytest.mark.edge_case
    def test_rejects_wrong_password(self, db, api_client, client_user):
        resp = api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "WrongPass!"},
            format="json",
        )
        assert resp.status_code == 401

    @pytest.mark.edge_case
    def test_rejects_unknown_email(self, db, api_client):
        resp = api_client.post(
            LOGIN_URL,
            {"email": "ghost@nobody.test", "password": "StrongPass123!"},
            format="json",
        )
        assert resp.status_code == 401

    @pytest.mark.edge_case
    def test_rejects_suspended_account(self, db, api_client, client_user):
        client_user.status = "suspended"
        client_user.save(update_fields=["status"])
        resp = api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "TestPass123!"},
            format="json",
        )
        assert resp.status_code == 400  # ValidationError -> 400 in our handler

    def test_email_is_lowercased_before_lookup(self, db, api_client, client_user):
        # Login with mixed-case email — should still authenticate
        resp = api_client.post(
            LOGIN_URL,
            {"email": client_user.email.upper(), "password": "TestPass123!"},
            format="json",
        )
        assert resp.status_code == 200


@pytest.mark.integration
class TestTokenRefresh:
    def test_refresh_returns_new_access_token(self, db, api_client, client_user):
        login = api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "TestPass123!"},
            format="json",
        )
        refresh = login.json()["refresh"]
        resp = api_client.post(REFRESH_URL, {"refresh": refresh}, format="json")
        assert resp.status_code == 200
        assert "access" in resp.json()

    @pytest.mark.edge_case
    def test_refresh_rejects_garbage_token(self, db, api_client):
        resp = api_client.post(REFRESH_URL, {"refresh": "not.a.valid.jwt"}, format="json")
        assert resp.status_code == 401
