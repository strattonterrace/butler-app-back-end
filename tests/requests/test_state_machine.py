"""ServiceRequest.can_transition_to() — the lifecycle state machine.

Mirrors the matrix in BACKEND_SCOPE §10. Every M3 status-transition endpoint
will call this — these tests pin down the rules so M3 can't accidentally
reinterpret them.
"""
import pytest

from apps.requests.models import ServiceRequest


@pytest.fixture
def request_factory(db):
    """Builds a ServiceRequest with sensible defaults — fixture not factory_boy
    to keep status/driver mutations explicit per test."""
    def _make(client, **kwargs):
        defaults = dict(
            service_type="grocery", title="t", description="d",
            pickup_location="p", dropoff_location="d",
        )
        defaults.update(kwargs)
        return ServiceRequest.objects.create(client=client, **defaults)
    return _make


@pytest.mark.unit
class TestForwardTransitions:
    def test_operator_can_review_submitted(self, db, request_factory, client_user, operator_user):
        req = request_factory(client_user, status="submitted")
        ok, code = req.can_transition_to("reviewed", operator_user)
        assert ok is True and code is None

    def test_admin_can_review_submitted(self, db, request_factory, client_user, admin_user):
        req = request_factory(client_user, status="submitted")
        ok, code = req.can_transition_to("reviewed", admin_user)
        assert ok is True and code is None

    def test_client_cannot_review_own_request(self, db, request_factory, client_user):
        req = request_factory(client_user, status="submitted")
        ok, code = req.can_transition_to("reviewed", client_user)
        assert ok is False and code == "PERMISSION_DENIED"

    def test_cannot_skip_states_submitted_to_assigned(
        self, db, request_factory, client_user, operator_user,
    ):
        req = request_factory(client_user, status="submitted")
        ok, code = req.can_transition_to("assigned", operator_user)
        assert ok is False and code == "REQ_INVALID_TRANSITION"

    def test_assigned_driver_can_start(self, db, request_factory, client_user, driver_user):
        req = request_factory(client_user, status="assigned", driver=driver_user)
        ok, code = req.can_transition_to("in_progress", driver_user)
        assert ok is True and code is None

    def test_other_driver_cannot_start(
        self, db, request_factory, client_user, driver_user,
    ):
        from tests.factories import DriverUserFactory
        other = DriverUserFactory()
        req = request_factory(client_user, status="assigned", driver=driver_user)
        ok, code = req.can_transition_to("in_progress", other)
        assert ok is False and code == "REQ_NOT_ASSIGNED_DRIVER"

    def test_operator_cannot_start_on_drivers_behalf(
        self, db, request_factory, client_user, driver_user, operator_user,
    ):
        req = request_factory(client_user, status="assigned", driver=driver_user)
        ok, code = req.can_transition_to("in_progress", operator_user)
        assert ok is False and code == "PERMISSION_DENIED"

    def test_assigned_driver_can_complete(
        self, db, request_factory, client_user, driver_user,
    ):
        req = request_factory(client_user, status="in_progress", driver=driver_user)
        ok, code = req.can_transition_to("completed", driver_user)
        assert ok is True and code is None

    def test_only_admin_can_close(
        self, db, request_factory, client_user, driver_user, operator_user, admin_user,
    ):
        req = request_factory(client_user, status="completed", driver=driver_user)
        assert req.can_transition_to("closed", admin_user) == (True, None)
        assert req.can_transition_to("closed", operator_user)[1] == "PERMISSION_DENIED"
        assert req.can_transition_to("closed", driver_user)[1] == "PERMISSION_DENIED"


@pytest.mark.unit
class TestCancellation:
    def test_client_can_cancel_own_submitted(self, db, request_factory, client_user):
        req = request_factory(client_user, status="submitted")
        ok, code = req.can_transition_to("cancelled", client_user)
        assert ok is True and code is None

    def test_client_can_cancel_own_reviewed(self, db, request_factory, client_user):
        req = request_factory(client_user, status="reviewed")
        ok, code = req.can_transition_to("cancelled", client_user)
        assert ok is True and code is None

    def test_client_cannot_cancel_after_assignment(
        self, db, request_factory, client_user, driver_user,
    ):
        req = request_factory(client_user, status="assigned", driver=driver_user)
        ok, code = req.can_transition_to("cancelled", client_user)
        assert ok is False and code == "REQ_INVALID_TRANSITION"

    def test_client_cannot_cancel_other_clients_request(self, db, request_factory, client_user):
        from tests.factories import ClientUserFactory
        other = ClientUserFactory()
        req = request_factory(client_user, status="submitted")
        ok, code = req.can_transition_to("cancelled", other)
        assert ok is False and code == "PERMISSION_DENIED"

    def test_operator_can_cancel_at_any_open_state(
        self, db, request_factory, client_user, driver_user, operator_user,
    ):
        for status in ["submitted", "reviewed", "assigned", "in_progress"]:
            req = request_factory(
                client_user, status=status,
                driver=driver_user if status in {"assigned", "in_progress"} else None,
            )
            ok, code = req.can_transition_to("cancelled", operator_user)
            assert ok is True, f"operator cancel failed at status={status}: {code}"

    def test_driver_cannot_cancel(self, db, request_factory, client_user, driver_user):
        req = request_factory(client_user, status="assigned", driver=driver_user)
        ok, code = req.can_transition_to("cancelled", driver_user)
        assert ok is False and code == "PERMISSION_DENIED"


@pytest.mark.unit
class TestTerminalStates:
    def test_cannot_transition_from_cancelled(
        self, db, request_factory, client_user, admin_user,
    ):
        req = request_factory(client_user, status="cancelled")
        ok, code = req.can_transition_to("reviewed", admin_user)
        assert ok is False and code == "REQ_ALREADY_CANCELLED"

    def test_cannot_transition_from_closed(
        self, db, request_factory, client_user, admin_user,
    ):
        req = request_factory(client_user, status="closed")
        ok, code = req.can_transition_to("in_progress", admin_user)
        assert ok is False and code == "REQ_INVALID_TRANSITION"

    def test_cannot_transition_to_same_state(
        self, db, request_factory, client_user, operator_user,
    ):
        req = request_factory(client_user, status="reviewed")
        ok, code = req.can_transition_to("reviewed", operator_user)
        assert ok is False and code == "REQ_INVALID_TRANSITION"


@pytest.mark.unit
class TestAllowedNextStatuses:
    def test_operator_from_submitted(self):
        nexts = ServiceRequest.allowed_next_statuses("submitted", "operator")
        assert "reviewed" in nexts
        assert "cancelled" in nexts
        assert "assigned" not in nexts

    def test_driver_from_assigned(self):
        nexts = ServiceRequest.allowed_next_statuses("assigned", "driver")
        assert nexts == ["in_progress"]

    def test_client_from_assigned_has_nothing(self):
        # Client can no longer cancel after assignment, can't move forward either
        nexts = ServiceRequest.allowed_next_statuses("assigned", "client")
        assert nexts == []

    def test_admin_from_completed_can_close(self):
        nexts = ServiceRequest.allowed_next_statuses("completed", "admin")
        assert "closed" in nexts
        assert "cancelled" in nexts
