"""Admin analytics routes — mounted at /api/v1/admin/."""
from django.urls import path

from .views import (
    AdminActivityView,
    AdminMetricsView,
    AdminReactivateUserView,
    AdminRevenueView,
    AdminSuspendUserView,
)

urlpatterns = [
    path("metrics/", AdminMetricsView.as_view(), name="admin-metrics"),
    path("revenue/", AdminRevenueView.as_view(), name="admin-revenue"),
    path("activity/", AdminActivityView.as_view(), name="admin-activity"),
    path("users/<uuid:pk>/suspend/", AdminSuspendUserView.as_view(), name="admin-suspend-user"),
    path("users/<uuid:pk>/reactivate/", AdminReactivateUserView.as_view(), name="admin-reactivate-user"),
]
