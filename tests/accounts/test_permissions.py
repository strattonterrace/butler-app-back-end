"""Role-based permission classes — exhaustive matrix."""
import pytest
from rest_framework.test import APIRequestFactory

from apps.accounts.permissions import (
    IsAdmin,
    IsAdminOrOperator,
    IsClient,
    IsDriver,
    IsOperator,
)


@pytest.fixture
def rf():
    return APIRequestFactory()


@pytest.mark.unit
@pytest.mark.parametrize(
    "permission_class,allowed_role",
    [
        (IsClient, "client"),
        (IsOperator, "operator"),
        (IsDriver, "driver"),
        (IsAdmin, "admin"),
    ],
)
def test_role_permission_allows_only_matching_role(
    db, rf, permission_class, allowed_role,
    client_user, operator_user, driver_user, admin_user,
):
    perm = permission_class()
    request = rf.get("/")

    role_to_user = {
        "client": client_user,
        "operator": operator_user,
        "driver": driver_user,
        "admin": admin_user,
    }
    for role, user in role_to_user.items():
        request.user = user
        assert perm.has_permission(request, view=None) is (role == allowed_role)


@pytest.mark.unit
def test_admin_or_operator_admits_both(db, rf, operator_user, admin_user, client_user):
    perm = IsAdminOrOperator()
    request = rf.get("/")

    request.user = admin_user
    assert perm.has_permission(request, view=None) is True

    request.user = operator_user
    assert perm.has_permission(request, view=None) is True

    request.user = client_user
    assert perm.has_permission(request, view=None) is False


@pytest.mark.unit
def test_unauthenticated_request_denied(rf):
    from django.contrib.auth.models import AnonymousUser
    request = rf.get("/")
    request.user = AnonymousUser()
    for perm_cls in (IsClient, IsOperator, IsDriver, IsAdmin, IsAdminOrOperator):
        assert perm_cls().has_permission(request, view=None) is False
