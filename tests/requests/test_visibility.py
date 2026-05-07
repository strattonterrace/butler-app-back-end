"""ServiceRequest.objects.visible_to() — the visibility matrix.

These tests are the architecture's load-bearing proof. If any of them fail,
M3 endpoints would leak data across roles or territories.
"""
import pytest

from apps.requests.models import ServiceRequest
from apps.territories.models import Territory
from tests.factories import (
    ClientUserFactory, DriverUserFactory, OperatorUserFactory,
)


@pytest.fixture
def territories(db):
    return {
        "oc": Territory.objects.create(name="Orange County, CA"),
        "la": Territory.objects.create(name="Los Angeles, CA"),
    }


@pytest.fixture
def world(db, territories):
    """Two territories, two of each role, two requests per client."""
    oc, la = territories["oc"], territories["la"]

    client_oc = ClientUserFactory(territory=oc)
    client_la = ClientUserFactory(territory=la)
    operator_oc = OperatorUserFactory(territory=oc)
    operator_la = OperatorUserFactory(territory=la)
    driver_oc = DriverUserFactory(territory=oc)
    driver_la = DriverUserFactory(territory=la)

    req_oc_1 = ServiceRequest.objects.create(
        client=client_oc, service_type="grocery", title="OC #1",
        description="x", pickup_location="x", dropoff_location="x",
    )
    req_oc_2 = ServiceRequest.objects.create(
        client=client_oc, driver=driver_oc, status="assigned",
        service_type="pharmacy", title="OC #2",
        description="x", pickup_location="x", dropoff_location="x",
    )
    req_la = ServiceRequest.objects.create(
        client=client_la, service_type="grocery", title="LA #1",
        description="x", pickup_location="x", dropoff_location="x",
    )
    return locals()


@pytest.mark.integration
class TestVisibility:
    def test_admin_sees_everything(self, db, world):
        from tests.factories import AdminUserFactory
        admin = AdminUserFactory()
        visible = ServiceRequest.objects.visible_to(admin)
        assert visible.count() == 3

    def test_client_sees_only_their_own_requests(self, db, world):
        client_oc = world["client_oc"]
        client_la = world["client_la"]
        oc_visible = ServiceRequest.objects.visible_to(client_oc)
        la_visible = ServiceRequest.objects.visible_to(client_la)

        assert oc_visible.count() == 2
        assert la_visible.count() == 1
        # Cross-client leak check
        assert world["req_la"] not in oc_visible
        assert world["req_oc_1"] not in la_visible

    def test_operator_sees_only_their_territory(self, db, world):
        operator_oc = world["operator_oc"]
        operator_la = world["operator_la"]

        oc_visible = ServiceRequest.objects.visible_to(operator_oc)
        la_visible = ServiceRequest.objects.visible_to(operator_la)

        assert oc_visible.count() == 2
        assert world["req_la"] not in oc_visible
        assert la_visible.count() == 1
        assert world["req_oc_1"] not in la_visible

    def test_operator_with_no_territory_sees_nothing(self, db, world):
        from tests.factories import OperatorUserFactory
        nomad = OperatorUserFactory(territory=None)
        assert ServiceRequest.objects.visible_to(nomad).count() == 0

    def test_driver_sees_only_assigned_to_them(self, db, world):
        driver_oc = world["driver_oc"]
        driver_la = world["driver_la"]

        assert ServiceRequest.objects.visible_to(driver_oc).count() == 1
        # driver_la has no assigned requests
        assert ServiceRequest.objects.visible_to(driver_la).count() == 0

    def test_anonymous_user_sees_nothing(self, db, world):
        from django.contrib.auth.models import AnonymousUser
        assert ServiceRequest.objects.visible_to(AnonymousUser()).count() == 0


@pytest.mark.integration
class TestAvailableForDriver:
    def test_approved_driver_sees_reviewed_unassigned_in_territory(self, db, world):
        from apps.drivers.models import DriverProfile

        driver = world["driver_oc"]
        DriverProfile.objects.create(
            user=driver, territory=world["territories"]["oc"],
            vehicle_make="Toyota", vehicle_model="Camry",
            vehicle_year=2022, license_plate="OC1",
            available_days=["monday"], approval_status="approved",
        )

        # Move req_oc_1 to "reviewed" so it's pickup-able
        world["req_oc_1"].status = "reviewed"
        world["req_oc_1"].save()

        available = ServiceRequest.objects.available_for_driver(driver)
        assert world["req_oc_1"] in available
        assert world["req_oc_2"] not in available  # already assigned
        assert world["req_la"] not in available  # different territory

    def test_unapproved_driver_sees_nothing(self, db, world):
        from apps.drivers.models import DriverProfile
        driver = world["driver_oc"]
        DriverProfile.objects.create(
            user=driver, territory=world["territories"]["oc"],
            vehicle_make="Toyota", vehicle_model="Camry",
            vehicle_year=2022, license_plate="OC1",
            available_days=["monday"], approval_status="pending",
        )
        world["req_oc_1"].status = "reviewed"
        world["req_oc_1"].save()

        assert ServiceRequest.objects.available_for_driver(driver).count() == 0

    def test_driver_without_profile_sees_nothing(self, db, world):
        # No DriverProfile exists for driver_oc
        assert ServiceRequest.objects.available_for_driver(world["driver_oc"]).count() == 0

    def test_non_driver_sees_nothing(self, db, world):
        # Client trying to view available orders
        assert ServiceRequest.objects.available_for_driver(world["client_oc"]).count() == 0
