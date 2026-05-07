"""Object-level permission tests — IsTerritoryScoped + IsRequestParticipant.

Both fail closed on missing territories. Cross-territory + cross-user
leakage is the failure mode these tests guard against.
"""
import pytest
from rest_framework.test import APIRequestFactory

from apps.accounts.permissions import IsRequestParticipant, IsTerritoryScoped
from apps.requests.models import ServiceRequest
from apps.territories.models import Territory
from tests.factories import (
    AdminUserFactory, ClientUserFactory, DriverUserFactory, OperatorUserFactory,
)


@pytest.fixture
def rf():
    return APIRequestFactory()


@pytest.fixture
def setup(db):
    oc = Territory.objects.create(name="Orange County, CA")
    la = Territory.objects.create(name="Los Angeles, CA")
    client_oc = ClientUserFactory(territory=oc)
    client_la = ClientUserFactory(territory=la)
    operator_oc = OperatorUserFactory(territory=oc)
    operator_la = OperatorUserFactory(territory=la)
    driver_oc = DriverUserFactory(territory=oc)
    admin = AdminUserFactory()
    req_oc = ServiceRequest.objects.create(
        client=client_oc, service_type="grocery", title="t",
        description="d", pickup_location="p", dropoff_location="d",
    )
    req_la = ServiceRequest.objects.create(
        client=client_la, service_type="grocery", title="t",
        description="d", pickup_location="p", dropoff_location="d",
    )
    return locals()


@pytest.mark.integration
class TestIsTerritoryScoped:
    def test_admin_always_passes(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["admin"]
        perm = IsTerritoryScoped()
        assert perm.has_object_permission(req, view=None, obj=setup["req_oc"]) is True
        assert perm.has_object_permission(req, view=None, obj=setup["req_la"]) is True

    def test_operator_in_oc_passes_for_oc_request(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["operator_oc"]
        assert IsTerritoryScoped().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is True

    def test_operator_in_oc_blocked_from_la_request(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["operator_oc"]
        assert IsTerritoryScoped().has_object_permission(
            req, view=None, obj=setup["req_la"],
        ) is False

    def test_operator_with_no_territory_denied(self, db, rf, setup):
        nomad = OperatorUserFactory(territory=None)
        req = rf.get("/")
        req.user = nomad
        assert IsTerritoryScoped().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is False


@pytest.mark.integration
class TestIsRequestParticipant:
    def test_admin_always_passes(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["admin"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is True

    def test_client_can_access_own_request(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["client_oc"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is True

    def test_client_blocked_from_other_clients_request(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["client_oc"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_la"],
        ) is False

    def test_driver_blocked_when_not_assigned(self, db, rf, setup):
        # driver_oc has no assigned requests in this fixture
        req = rf.get("/")
        req.user = setup["driver_oc"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is False

    def test_driver_can_access_assigned_request(self, db, rf, setup):
        # Assign a request to driver_oc
        setup["req_oc"].driver = setup["driver_oc"]
        setup["req_oc"].status = "assigned"
        setup["req_oc"].save()

        req = rf.get("/")
        req.user = setup["driver_oc"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is True

    def test_operator_in_oc_can_access_oc_request(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["operator_oc"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_oc"],
        ) is True

    def test_operator_in_oc_blocked_from_la_request(self, db, rf, setup):
        req = rf.get("/")
        req.user = setup["operator_oc"]
        assert IsRequestParticipant().has_object_permission(
            req, view=None, obj=setup["req_la"],
        ) is False
