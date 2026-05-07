"""Shared pytest fixtures."""
import pytest
from rest_framework.test import APIClient

from .factories import (
    AdminUserFactory,
    ClientUserFactory,
    DriverUserFactory,
    OperatorUserFactory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client():
    """Returns a function that takes a user and returns an authenticated APIClient."""
    def _auth(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client
    return _auth


@pytest.fixture
def client_user(db):
    return ClientUserFactory()


@pytest.fixture
def operator_user(db):
    return OperatorUserFactory()


@pytest.fixture
def driver_user(db):
    return DriverUserFactory()


@pytest.fixture
def admin_user(db):
    return AdminUserFactory()
