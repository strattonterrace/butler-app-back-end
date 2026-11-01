"""Saved-address book — /api/v1/users/me/addresses/ (client address book)."""
import pytest

from apps.accounts.models import SavedAddress

pytestmark = pytest.mark.django_db

LIST = "/api/v1/users/me/addresses/"


def detail(pk):
    return f"/api/v1/users/me/addresses/{pk}/"


class TestAddressBook:
    def test_requires_auth(self, api_client):
        assert api_client.get(LIST).status_code == 401

    def test_create_and_list(self, auth_client, client_user):
        c = auth_client(client_user)
        resp = c.post(LIST, {"label": "Home", "address": "1 Main St, Irvine CA"}, format="json")
        assert resp.status_code == 201
        assert resp.json()["label"] == "Home"

        listed = c.get(LIST).json()
        assert len(listed) == 1
        assert listed[0]["address"].startswith("1 Main St")

    def test_list_scoped_to_owner(self, auth_client, client_user, operator_user):
        SavedAddress.objects.create(user=client_user, label="Home", address="A")
        assert auth_client(operator_user).get(LIST).json() == []

    def test_set_default_clears_previous(self, auth_client, client_user):
        c = auth_client(client_user)
        c.post(LIST, {"label": "Home", "address": "A", "isDefault": True}, format="json")
        b = c.post(LIST, {"label": "Work", "address": "B", "isDefault": True}, format="json").json()

        defaults = SavedAddress.objects.filter(user=client_user, is_default=True)
        assert defaults.count() == 1
        assert str(defaults.first().id) == b["id"]

    def test_update(self, auth_client, client_user):
        c = auth_client(client_user)
        a = c.post(LIST, {"label": "Home", "address": "A"}, format="json").json()
        resp = c.patch(detail(a["id"]), {"label": "House"}, format="json")
        assert resp.status_code == 200
        assert resp.json()["label"] == "House"

    def test_delete(self, auth_client, client_user):
        c = auth_client(client_user)
        a = c.post(LIST, {"label": "Home", "address": "A"}, format="json").json()
        assert c.delete(detail(a["id"])).status_code == 204
        assert SavedAddress.objects.filter(user=client_user).count() == 0

    def test_cannot_touch_another_users_address(self, auth_client, client_user, operator_user):
        addr = SavedAddress.objects.create(user=client_user, label="Home", address="A")
        intruder = auth_client(operator_user)
        assert intruder.patch(detail(addr.id), {"label": "X"}, format="json").status_code == 404
        assert intruder.delete(detail(addr.id)).status_code == 404

    def test_blank_label_rejected(self, auth_client, client_user):
        resp = auth_client(client_user).post(LIST, {"label": "   ", "address": "A"}, format="json")
        assert resp.status_code == 400
