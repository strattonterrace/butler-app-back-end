"""POST /api/v1/requests/ — creation, gating, validation (§10)."""
import pytest

from apps.activity.models import ActivityLog
from apps.requests.models import ServiceRequest, StatusHistory
from apps.subscriptions.models import Subscription
from tests.factories import ClientUserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/requests/"

VALID_BODY = {
    "service_type": "grocery",
    "title": "Pick up groceries from Trader Joe's",
    "description": "Weekly groceries, see list in notes",
    "pickup_location": "Trader Joe's, Newport Beach",
    "dropoff_location": "123 Main St, Irvine, CA 92618",
    "urgency": "asap",
    "special_instructions": "Get organic milk if available",
    "estimated_budget": "$80-100",
}


class TestCreateRequest:
    def test_active_client_creates_request(self, auth_client, territory_client):
        resp = auth_client(territory_client).post(URL, VALID_BODY, format="json")

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "submitted"
        assert data["serviceType"] == "grocery"
        assert data["client"]["id"] == str(territory_client.id)
        assert data["driver"] is None
        assert data["operator"] is None

        sr = ServiceRequest.objects.get(id=data["id"])
        assert sr.client == territory_client
        assert sr.status == "submitted"

    def test_create_writes_opening_history_entry(self, auth_client, territory_client):
        resp = auth_client(territory_client).post(URL, VALID_BODY, format="json")
        sr = ServiceRequest.objects.get(id=resp.json()["id"])

        history = StatusHistory.objects.filter(request=sr)
        assert history.count() == 1
        entry = history.get()
        assert entry.from_status is None
        assert entry.to_status == "submitted"
        assert entry.changed_by == territory_client

        # Detail response carries the timeline
        assert len(resp.json()["statusHistory"]) == 1

    def test_create_emits_activity_event(self, auth_client, territory_client):
        resp = auth_client(territory_client).post(URL, VALID_BODY, format="json")
        assert ActivityLog.objects.filter(
            type="order_submitted",
            target_request_id=resp.json()["id"],
        ).exists()

    def test_inactive_subscription_blocked(self, auth_client, db):
        client = ClientUserFactory()
        Subscription.objects.update_or_create(
            user=client, defaults={"status": "inactive"},
        )
        resp = auth_client(client).post(URL, VALID_BODY, format="json")
        assert resp.status_code == 403

    def test_past_due_subscription_blocked(self, auth_client, db):
        client = ClientUserFactory()
        Subscription.objects.update_or_create(
            user=client, defaults={"status": "past_due"},
        )
        resp = auth_client(client).post(URL, VALID_BODY, format="json")
        assert resp.status_code == 403

    def test_non_client_roles_cannot_create(
        self, auth_client, territory_operator, approved_driver, admin_user,
    ):
        for user in (territory_operator, approved_driver, admin_user):
            resp = auth_client(user).post(URL, VALID_BODY, format="json")
            assert resp.status_code == 403, user.role

    def test_anonymous_cannot_create(self, api_client, db):
        resp = api_client.post(URL, VALID_BODY, format="json")
        assert resp.status_code == 401

    def test_scheduled_requires_date_and_window(self, auth_client, territory_client):
        body = {**VALID_BODY, "urgency": "scheduled"}
        resp = auth_client(territory_client).post(URL, body, format="json")

        assert resp.status_code == 400
        errors = resp.json()["errors"]
        assert "scheduledDate" in errors
        assert "scheduledWindow" in errors

    def test_scheduled_with_date_and_window_ok(self, auth_client, territory_client):
        body = {
            **VALID_BODY,
            "urgency": "scheduled",
            "scheduled_date": "2026-07-20",
            "scheduled_window": "morning",
        }
        resp = auth_client(territory_client).post(URL, body, format="json")
        assert resp.status_code == 201
        assert resp.json()["scheduledDate"] == "2026-07-20"

    def test_asap_request_drops_stray_schedule_fields(self, auth_client, territory_client):
        body = {
            **VALID_BODY,
            "scheduled_date": "2026-07-20",
            "scheduled_window": "morning",
        }
        resp = auth_client(territory_client).post(URL, body, format="json")
        assert resp.status_code == 201
        assert resp.json()["scheduledDate"] is None
        assert resp.json()["scheduledWindow"] is None

    def test_missing_required_fields_rejected(self, auth_client, territory_client):
        resp = auth_client(territory_client).post(
            URL, {"service_type": "grocery"}, format="json",
        )
        assert resp.status_code == 400
        errors = resp.json()["errors"]
        for field in ("title", "description", "pickupLocation", "dropoffLocation"):
            assert field in errors

    def test_invalid_service_type_rejected(self, auth_client, territory_client):
        body = {**VALID_BODY, "service_type": "helicopter_rental"}
        resp = auth_client(territory_client).post(URL, body, format="json")
        assert resp.status_code == 400
