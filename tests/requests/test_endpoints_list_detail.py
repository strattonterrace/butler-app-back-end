"""GET /api/v1/requests/ + /:id/ + /:id/history/ — visibility & shapes."""
import pytest

from tests.factories import (
    ClientUserFactory,
    DriverProfileFactory,
    OperatorUserFactory,
    ServiceRequestFactory,
    TerritoryFactory,
)

pytestmark = pytest.mark.django_db

URL = "/api/v1/requests/"


def results(resp):
    return resp.json()["data"]["results"]


class TestListVisibility:
    def test_client_sees_only_own_requests(self, auth_client, territory_client):
        mine = ServiceRequestFactory(client=territory_client)
        ServiceRequestFactory()  # someone else's

        resp = auth_client(territory_client).get(URL)
        assert resp.status_code == 200
        ids = [r["id"] for r in results(resp)]
        assert ids == [str(mine.id)]

    def test_driver_sees_only_assigned_requests(self, auth_client, approved_driver, territory_client):
        assigned = ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        ServiceRequestFactory(client=territory_client)  # unassigned

        resp = auth_client(approved_driver).get(URL)
        ids = [r["id"] for r in results(resp)]
        assert ids == [str(assigned.id)]

    def test_operator_scoped_to_territory(self, auth_client, territory_operator, territory_client):
        in_territory = ServiceRequestFactory(client=territory_client)
        foreign_client = ClientUserFactory(territory=TerritoryFactory())
        ServiceRequestFactory(client=foreign_client)

        resp = auth_client(territory_operator).get(URL)
        ids = [r["id"] for r in results(resp)]
        assert ids == [str(in_territory.id)]

    def test_operator_without_territory_sees_nothing(self, auth_client, territory_client):
        ServiceRequestFactory(client=territory_client)
        homeless_op = OperatorUserFactory(territory=None)

        resp = auth_client(homeless_op).get(URL)
        assert results(resp) == []

    def test_admin_sees_everything(self, auth_client, admin_user, territory_client):
        ServiceRequestFactory(client=territory_client)
        ServiceRequestFactory()

        resp = auth_client(admin_user).get(URL)
        assert len(results(resp)) == 2

    def test_anonymous_rejected(self, api_client, db):
        assert api_client.get(URL).status_code == 401


class TestListFilters:
    def test_filter_by_status(self, auth_client, territory_client):
        ServiceRequestFactory(client=territory_client, status="submitted")
        done = ServiceRequestFactory(client=territory_client, status="completed")

        resp = auth_client(territory_client).get(URL, {"status": "completed"})
        ids = [r["id"] for r in results(resp)]
        assert ids == [str(done.id)]

    def test_filter_by_service_type(self, auth_client, territory_client):
        ServiceRequestFactory(client=territory_client, service_type="grocery")
        rx = ServiceRequestFactory(client=territory_client, service_type="pharmacy")

        resp = auth_client(territory_client).get(URL, {"service_type": "pharmacy"})
        ids = [r["id"] for r in results(resp)]
        assert ids == [str(rx.id)]

    def test_search_by_title(self, auth_client, territory_client):
        ServiceRequestFactory(client=territory_client, title="Dry cleaning run")
        hit = ServiceRequestFactory(client=territory_client, title="Costco mega haul")

        resp = auth_client(territory_client).get(URL, {"search": "costco"})
        ids = [r["id"] for r in results(resp)]
        assert ids == [str(hit.id)]

    def test_list_shape_matches_frontend_mock(self, auth_client, territory_client, approved_driver):
        ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        row = results(auth_client(territory_client).get(URL))[0]
        # Keys the dashboards read off MOCK_REQUESTS today
        for key in ("id", "title", "serviceType", "status", "dropoffLocation",
                    "createdAt", "clientName", "driverName"):
            assert key in row
        assert row["driverName"] == approved_driver.full_name


class TestDetail:
    def test_client_gets_own_detail_with_parties_and_history(
        self, auth_client, territory_client, approved_driver,
    ):
        sr = ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        resp = auth_client(territory_client).get(f"{URL}{sr.id}/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["client"]["fullName"] == territory_client.full_name
        assert data["driver"]["fullName"] == approved_driver.full_name
        assert "vehicle" in data["driver"]
        assert "statusHistory" in data
        assert "allowedTransitions" in data

    def test_other_clients_detail_is_404(self, auth_client, db):
        sr = ServiceRequestFactory()
        stranger = ClientUserFactory()
        assert auth_client(stranger).get(f"{URL}{sr.id}/").status_code == 404

    def test_driver_reads_assigned_request(self, auth_client, territory_client, approved_driver):
        sr = ServiceRequestFactory(
            client=territory_client, status="assigned", driver=approved_driver,
        )
        assert auth_client(approved_driver).get(f"{URL}{sr.id}/").status_code == 200

    def test_allowed_transitions_reflect_role(self, auth_client, territory_client, admin_user):
        sr = ServiceRequestFactory(client=territory_client)  # submitted

        as_client = auth_client(territory_client).get(f"{URL}{sr.id}/").json()
        assert as_client["allowedTransitions"] == ["cancelled"]

        as_admin = auth_client(admin_user).get(f"{URL}{sr.id}/").json()
        assert set(as_admin["allowedTransitions"]) == {"reviewed", "cancelled"}


class TestHistoryEndpoint:
    def test_history_returns_flat_timeline(self, auth_client, territory_client, territory_operator):
        sr = ServiceRequestFactory(client=territory_client)
        auth_client(territory_operator).patch(
            f"{URL}{sr.id}/status/", {"status": "reviewed"}, format="json",
        )

        resp = auth_client(territory_client).get(f"{URL}{sr.id}/history/")
        assert resp.status_code == 200
        timeline = resp.json()
        assert isinstance(timeline, list)
        assert timeline[-1]["toStatus"] == "reviewed"
        assert timeline[-1]["changedBy"]["role"] == "operator"

    def test_history_hidden_for_strangers(self, auth_client, db):
        sr = ServiceRequestFactory()
        stranger = ClientUserFactory()
        assert auth_client(stranger).get(f"{URL}{sr.id}/history/").status_code == 404
