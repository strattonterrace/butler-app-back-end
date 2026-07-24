"""Shared fixtures for request lifecycle endpoint tests."""
import pytest

from apps.subscriptions.models import Subscription
from tests.factories import (
    ClientUserFactory,
    DriverProfileFactory,
    OperatorUserFactory,
    TerritoryFactory,
)


@pytest.fixture
def territory(db):
    return TerritoryFactory()


@pytest.fixture
def territory_operator(db, territory):
    return OperatorUserFactory(territory=territory)


@pytest.fixture
def territory_client(db, territory):
    """Client in `territory` with an ACTIVE subscription (can create requests)."""
    user = ClientUserFactory(territory=territory)
    Subscription.objects.update_or_create(
        user=user, defaults={"status": "active"},
    )
    return user


@pytest.fixture
def approved_driver(db, territory):
    """Approved driver working `territory`."""
    profile = DriverProfileFactory(territory=territory)
    return profile.user
