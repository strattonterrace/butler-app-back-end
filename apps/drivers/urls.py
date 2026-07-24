"""Driver routes — mounted at /api/v1/drivers/."""
from django.urls import path

from .views import (
    ApplicationStatusView,
    ApproveDriverView,
    AvailableDriversView,
    DriverApplyView,
    PendingDriversView,
    RejectDriverView,
)

urlpatterns = [
    path("apply/", DriverApplyView.as_view(), name="driver-apply"),
    path("application-status/", ApplicationStatusView.as_view(), name="driver-application-status"),
    path("available/", AvailableDriversView.as_view(), name="driver-available"),
    path("pending/", PendingDriversView.as_view(), name="driver-pending"),
    path("<uuid:pk>/approve/", ApproveDriverView.as_view(), name="driver-approve"),
    path("<uuid:pk>/reject/", RejectDriverView.as_view(), name="driver-reject"),
]
