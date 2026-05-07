"""User manager — role + territory scoping."""
import pytest

from apps.accounts.models import User
from apps.territories.models import Territory


@pytest.fixture
def two_territories(db):
    oc = Territory.objects.create(name="Orange County, CA")
    la = Territory.objects.create(name="Los Angeles, CA")
    return oc, la


@pytest.mark.unit
class TestUserManager:
    def test_clients_filters_to_clients_only(
        self, db, client_user, operator_user, driver_user, admin_user,
    ):
        clients = User.objects.clients()
        assert client_user in clients
        assert operator_user not in clients
        assert driver_user not in clients
        assert admin_user not in clients

    def test_in_territory_returns_none_for_null_territory(self, db, client_user):
        assert User.objects.in_territory(None).count() == 0

    def test_in_territory_filters_to_matching_territory(
        self, db, two_territories, client_user, operator_user,
    ):
        oc, la = two_territories
        client_user.territory = oc
        client_user.save(update_fields=["territory"])
        operator_user.territory = la
        operator_user.save(update_fields=["territory"])

        in_oc = User.objects.in_territory(oc)
        assert client_user in in_oc
        assert operator_user not in in_oc

    def test_for_operator_returns_only_operators_territory(
        self, db, two_territories,
        client_user, operator_user, driver_user,
    ):
        oc, la = two_territories
        operator_user.territory = oc
        operator_user.save(update_fields=["territory"])
        client_user.territory = oc
        client_user.save(update_fields=["territory"])
        driver_user.territory = la
        driver_user.save(update_fields=["territory"])

        scoped = User.objects.for_operator(operator_user)
        assert client_user in scoped
        assert driver_user not in scoped

    def test_for_operator_with_no_territory_returns_empty(
        self, db, operator_user, client_user,
    ):
        # operator_user has no territory by default
        assert User.objects.for_operator(operator_user).count() == 0

    def test_chainable_with_filters(self, db, two_territories, client_user, driver_user):
        oc, _ = two_territories
        client_user.territory = oc
        client_user.save(update_fields=["territory"])
        driver_user.territory = oc
        driver_user.save(update_fields=["territory"])

        # Combine queryset methods
        clients_in_oc = User.objects.clients().in_territory(oc)
        assert client_user in clients_in_oc
        assert driver_user not in clients_in_oc
