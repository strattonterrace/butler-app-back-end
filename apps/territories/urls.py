"""Territory URL routes — mounted at /api/v1/territories/."""
from django.urls import path

from .views import ServedAreasView, TerritoryCheckView, WaitlistJoinView

urlpatterns = [
    path("served/", ServedAreasView.as_view(), name="territories-served"),
    path("check/", TerritoryCheckView.as_view(), name="territories-check"),
    path("waitlist/", WaitlistJoinView.as_view(), name="territories-waitlist"),
]
