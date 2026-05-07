"""POST /api/v1/auth/password-reset/ + confirm flow."""
import pytest
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

REQUEST_URL = reverse("auth-password-reset")
CONFIRM_URL = reverse("auth-password-reset-confirm")
LOGIN_URL = reverse("auth-login")


@pytest.mark.integration
class TestPasswordReset:
    def test_request_returns_200_for_existing_email(self, db, api_client, client_user):
        resp = api_client.post(REQUEST_URL, {"email": client_user.email}, format="json")
        assert resp.status_code == 200

    @pytest.mark.edge_case
    def test_request_returns_200_for_unknown_email(self, db, api_client):
        # Must not reveal whether the email exists
        resp = api_client.post(REQUEST_URL, {"email": "ghost@nobody.test"}, format="json")
        assert resp.status_code == 200

    def test_confirm_resets_password_with_valid_token(self, db, api_client, client_user):
        uid = urlsafe_base64_encode(force_bytes(client_user.pk))
        token = default_token_generator.make_token(client_user)

        resp = api_client.post(
            CONFIRM_URL,
            {
                "uid": uid,
                "token": token,
                "password": "BrandNewPass123!",
                "confirmPassword": "BrandNewPass123!",
            },
            format="json",
        )
        assert resp.status_code == 200

        # New password should authenticate
        login = api_client.post(
            LOGIN_URL,
            {"email": client_user.email, "password": "BrandNewPass123!"},
            format="json",
        )
        assert login.status_code == 200

    @pytest.mark.edge_case
    def test_confirm_rejects_bad_token(self, db, api_client, client_user):
        uid = urlsafe_base64_encode(force_bytes(client_user.pk))
        resp = api_client.post(
            CONFIRM_URL,
            {
                "uid": uid,
                "token": "garbage-token",
                "password": "BrandNewPass123!",
                "confirmPassword": "BrandNewPass123!",
            },
            format="json",
        )
        assert resp.status_code == 400

    @pytest.mark.edge_case
    def test_confirm_rejects_mismatched_passwords(self, db, api_client, client_user):
        uid = urlsafe_base64_encode(force_bytes(client_user.pk))
        token = default_token_generator.make_token(client_user)
        resp = api_client.post(
            CONFIRM_URL,
            {
                "uid": uid,
                "token": token,
                "password": "OnePass123!",
                "confirmPassword": "DifferentPass123!",
            },
            format="json",
        )
        assert resp.status_code == 400
