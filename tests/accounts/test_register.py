"""POST /api/v1/auth/register/ — happy path + edge cases."""
import pytest
from django.urls import reverse

from apps.accounts.models import User

REGISTER_URL = reverse("auth-register")


@pytest.mark.integration
class TestRegister:
    def test_registers_client_with_valid_data(self, db, api_client):
        # Frontend speaks camelCase — the camel-case parser converts on the way in
        payload = {
            "email": "Jane@Example.com",
            "password": "StrongPass123!",
            "confirmPassword": "StrongPass123!",
            "fullName": "Jane Smith",
        }
        resp = api_client.post(REGISTER_URL, payload, format="json")
        assert resp.status_code == 201
        body = resp.json()
        assert body["user"]["role"] == "client"
        assert body["user"]["fullName"] == "Jane Smith"   # camelCase response key
        assert body["user"]["email"] == "jane@example.com"  # lowercased on save
        assert "access" in body and "refresh" in body
        assert User.objects.filter(email="jane@example.com").exists()

    @pytest.mark.edge_case
    def test_rejects_duplicate_email(self, db, api_client, client_user):
        payload = {
            "email": client_user.email,
            "password": "StrongPass123!",
            "confirmPassword": "StrongPass123!",
            "fullName": "Other Person",
        }
        resp = api_client.post(REGISTER_URL, payload, format="json")
        assert resp.status_code == 400
        assert "email" in resp.json()["errors"]

    @pytest.mark.edge_case
    def test_rejects_mismatched_passwords(self, db, api_client):
        payload = {
            "email": "x@example.com",
            "password": "StrongPass123!",
            "confirmPassword": "Different!",
            "fullName": "X User",
        }
        resp = api_client.post(REGISTER_URL, payload, format="json")
        assert resp.status_code == 400
        # Field name in the error dict is also camelCase on the wire
        assert "confirmPassword" in resp.json()["errors"]

    @pytest.mark.edge_case
    def test_rejects_weak_password(self, db, api_client):
        payload = {
            "email": "weak@example.com",
            "password": "abc",
            "confirmPassword": "abc",
            "fullName": "Weak User",
        }
        resp = api_client.post(REGISTER_URL, payload, format="json")
        assert resp.status_code == 400

    @pytest.mark.edge_case
    def test_rejects_invalid_email_format(self, db, api_client):
        payload = {
            "email": "not-an-email",
            "password": "StrongPass123!",
            "confirmPassword": "StrongPass123!",
            "fullName": "Bad Email",
        }
        resp = api_client.post(REGISTER_URL, payload, format="json")
        assert resp.status_code == 400
        assert "email" in resp.json()["errors"]
