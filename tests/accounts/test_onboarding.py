"""Client onboarding-complete endpoint (POST /auth/onboarding/)."""
import pytest

from apps.accounts.models import SavedAddress
from tests.factories import ClientUserFactory, TerritoryFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/onboarding/"


class TestOnboarding:
    def test_completes_and_assigns_territory(self, auth_client):
        client = ClientUserFactory(onboarding_completed=False, territory=None)
        territory = TerritoryFactory(name="Orange County, CA", zip_codes=["92618"])

        resp = auth_client(client).post(URL, {
            "territoryId": str(territory.id),
            "address": "456 Main St, Irvine, CA 92618",
            "preferredServices": ["grocery", "pharmacy"],
        }, format="json")

        assert resp.status_code == 200
        body = resp.json()
        assert body["onboardingCompleted"] is True
        assert body["preferredServices"] == ["grocery", "pharmacy"]

        client.refresh_from_db()
        assert client.territory_id == territory.id
        assert client.onboarding_completed is True

    def test_saves_default_home_address(self, auth_client):
        client = ClientUserFactory(territory=None)
        territory = TerritoryFactory(zip_codes=["92618"])
        auth_client(client).post(URL, {
            "territoryId": str(territory.id),
            "address": "789 Oak Ave, Costa Mesa, CA",
        }, format="json")

        addr = SavedAddress.objects.get(user=client, label="Home")
        assert addr.is_default is True
        assert "Oak Ave" in addr.address

    def test_unknown_territory_rejected(self, auth_client):
        client = ClientUserFactory()
        resp = auth_client(client).post(URL, {
            "territoryId": "00000000-0000-0000-0000-000000000000",
        }, format="json")
        assert resp.status_code == 400
        assert resp.json()["code"] == "TERRITORY_NOT_SERVED"

    def test_requires_auth(self, api_client):
        assert api_client.post(URL, {"territoryId": "x"}, format="json").status_code == 401

    def test_address_optional(self, auth_client):
        client = ClientUserFactory(territory=None)
        territory = TerritoryFactory(zip_codes=["92618"])
        resp = auth_client(client).post(URL, {"territoryId": str(territory.id)}, format="json")
        assert resp.status_code == 200
        assert not SavedAddress.objects.filter(user=client).exists()
