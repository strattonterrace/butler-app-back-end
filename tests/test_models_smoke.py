"""Smoke tests — every model can be instantiated and saved.

Catches missing migrations and broken FKs early.
"""
import pytest

from apps.activity.models import ActivityLog, ActivityType
from apps.drivers.models import DriverProfile
from apps.requests.models import RequestStatus, ServiceRequest, ServiceType, StatusHistory
from apps.subscriptions.models import Subscription
from apps.territories.models import Territory


@pytest.mark.integration
def test_territory_save(db, operator_user):
    t = Territory.objects.create(name="Orange County, CA", operator=operator_user)
    assert t.id is not None
    assert t.commission_rate == 0.20


@pytest.mark.integration
def test_subscription_save(db, client_user):
    sub = Subscription.objects.create(
        user=client_user,
        stripe_customer_id="cus_test_123",
    )
    assert sub.status == "inactive"
    assert sub.plan_amount == 199


@pytest.mark.integration
def test_service_request_with_history(db, client_user, operator_user):
    req = ServiceRequest.objects.create(
        client=client_user,
        service_type=ServiceType.GROCERY,
        title="Test request",
        description="Whole Foods order",
        pickup_location="Whole Foods, Irvine",
        dropoff_location="100 Main St, Irvine",
    )
    StatusHistory.objects.create(
        request=req,
        from_status=None,
        to_status=RequestStatus.SUBMITTED,
        changed_by=client_user,
    )
    assert req.status_history.count() == 1


@pytest.mark.integration
def test_driver_profile_save(db, driver_user):
    profile = DriverProfile.objects.create(
        user=driver_user,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        vehicle_year=2022,
        license_plate="7ABC123",
        available_days=["monday", "tuesday", "wednesday"],
    )
    assert profile.approval_status == "pending"
    assert profile.is_approved is False


@pytest.mark.integration
def test_activity_log_save(db, client_user):
    log = ActivityLog.objects.create(
        type=ActivityType.SUBSCRIPTION_NEW,
        message=f"New subscriber: {client_user.full_name} ($199/mo)",
        actor=client_user,
        metadata={"plan": "199"},
    )
    assert log.id is not None
    assert log.target_request is None
    assert ActivityLog.objects.filter(type="subscription_new").count() == 1
