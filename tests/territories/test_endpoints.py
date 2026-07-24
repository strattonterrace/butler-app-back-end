"""Public territory endpoints — the onboarding location gate + waitlist."""
import pytest

from apps.territories.models import TerritoryStatus, WaitlistEntry
from tests.factories import TerritoryFactory

pytestmark = pytest.mark.django_db

SERVED = "/api/v1/territories/served/"
CHECK = "/api/v1/territories/check/"
WAITLIST = "/api/v1/territories/waitlist/"


class TestServedAreas:
    def test_lists_active_territories_publicly(self, api_client):
        TerritoryFactory(name="Orange County, CA", status=TerritoryStatus.ACTIVE)
        TerritoryFactory(name="Dormant County", status=TerritoryStatus.INACTIVE)
        resp = api_client.get(SERVED)
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert "Orange County, CA" in names
        assert "Dormant County" not in names


class TestTerritoryCheck:
    def test_served_zip_returns_territory(self, api_client):
        TerritoryFactory(name="Orange County, CA", zip_codes=["92618", "92660"])
        data = api_client.get(CHECK, {"zip": "92618"}).json()
        assert data["served"] is True
        assert data["territory"]["name"] == "Orange County, CA"

    def test_unserved_zip_returns_false(self, api_client):
        TerritoryFactory(zip_codes=["92618"])
        data = api_client.get(CHECK, {"zip": "10001"}).json()
        assert data["served"] is False
        assert data["territory"] is None

    def test_inactive_territory_does_not_serve(self, api_client):
        TerritoryFactory(zip_codes=["92618"], status=TerritoryStatus.INACTIVE)
        assert api_client.get(CHECK, {"zip": "92618"}).json()["served"] is False

    def test_missing_zip_400(self, api_client):
        resp = api_client.get(CHECK)
        assert resp.status_code == 400
        assert resp.json()["code"] == "ZIP_REQUIRED"


class TestWaitlist:
    def test_join_creates_entry(self, api_client):
        resp = api_client.post(
            WAITLIST, {"email": "nyc@example.com", "zipCode": "10001", "note": "want it"},
            format="json",
        )
        assert resp.status_code == 201
        assert WaitlistEntry.objects.filter(email="nyc@example.com").exists()

    def test_join_is_idempotent(self, api_client):
        body = {"email": "dup@example.com", "zipCode": "10001"}
        api_client.post(WAITLIST, body, format="json")
        api_client.post(WAITLIST, body, format="json")
        assert WaitlistEntry.objects.filter(email="dup@example.com").count() == 1
