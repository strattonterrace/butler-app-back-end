"""Request lifecycle URLs — mounted at /api/v1/requests/."""
from django.urls import path

from .views import (
    RequestDetailView,
    RequestHistoryView,
    RequestListCreateView,
    RequestStatsView,
    RequestStatusView,
)

urlpatterns = [
    path("", RequestListCreateView.as_view(), name="request-list-create"),
    # stats/ must precede <uuid:pk>/ so it never resolves as a request id
    path("stats/", RequestStatsView.as_view(), name="request-stats"),
    path("<uuid:pk>/", RequestDetailView.as_view(), name="request-detail"),
    path("<uuid:pk>/status/", RequestStatusView.as_view(), name="request-status"),
    path("<uuid:pk>/history/", RequestHistoryView.as_view(), name="request-history"),
]
