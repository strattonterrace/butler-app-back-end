"""DriverProfile manager — approval + territory scoping."""
import pytest

from apps.drivers.models import DriverProfile
from apps.territories.models import Territory
from tests.factories import DriverUserFactory, OperatorUserFactory


@pytest.fixture
def setup(db):
    oc = Territory.objects.create(name="Orange County, CA")
    la = Territory.objects.create(name="Los Angeles, CA")

    def _profile(territory, status):
        user = DriverUserFactory(territory=territory)
        return DriverProfile.objects.create(
            user=user, territory=territory,
            vehicle_make="Toyota", vehicle_model="Camry",
            vehicle_year=2022, license_plate=f"PL{status[0].upper()}",
            available_days=["monday"], approval_status=status,
        )

    return {
        "oc": oc, "la": la,
        "approved_oc": _profile(oc, "approved"),
        "pending_oc":  _profile(oc, "pending"),
        "approved_la": _profile(la, "approved"),
        "rejected_oc": _profile(oc, "rejected"),
    }


@pytest.mark.unit
class TestDriverProfileManager:
    def test_approved_filters_to_approved(self, db, setup):
        approved = DriverProfile.objects.approved()
        assert setup["approved_oc"] in approved
        assert setup["approved_la"] in approved
        assert setup["pending_oc"] not in approved
        assert setup["rejected_oc"] not in approved

    def test_in_territory_returns_none_for_null(self, db, setup):
        assert DriverProfile.objects.in_territory(None).count() == 0

    def test_approved_in_territory_combines_filters(self, db, setup):
        result = DriverProfile.objects.approved_in_territory(setup["oc"])
        assert setup["approved_oc"] in result
        assert setup["pending_oc"] not in result    # wrong status
        assert setup["approved_la"] not in result   # wrong territory

    def test_for_operator_returns_approved_in_their_territory(self, db, setup):
        operator = OperatorUserFactory(territory=setup["oc"])
        result = DriverProfile.objects.for_operator(operator)
        assert setup["approved_oc"] in result
        assert setup["pending_oc"] not in result
        assert setup["approved_la"] not in result

    def test_for_operator_with_no_territory_returns_empty(self, db, setup):
        operator = OperatorUserFactory(territory=None)
        assert DriverProfile.objects.for_operator(operator).count() == 0

    def test_chainable(self, db, setup):
        result = (
            DriverProfile.objects
            .approved()
            .in_territory(setup["oc"])
            .filter(vehicle_make="Toyota")
        )
        assert setup["approved_oc"] in result
