"""User routes — mounted at /api/v1/users/"""
from django.urls import path

from .views import (
    AddressDetailView,
    AddressListCreateView,
    CreateOperatorView,
    MeView,
    UserDetailView,
    UserListView,
)

urlpatterns = [
    path("me/", MeView.as_view(), name="users-me"),
    # Address book — literal paths declared before the <uuid:pk> catch-all.
    path("me/addresses/", AddressListCreateView.as_view(), name="addresses-list"),
    path("me/addresses/<uuid:pk>/", AddressDetailView.as_view(), name="addresses-detail"),
    path("", UserListView.as_view(), name="users-list"),
    path("create-operator/", CreateOperatorView.as_view(), name="users-create-operator"),
    path("<uuid:pk>/", UserDetailView.as_view(), name="users-detail"),
]
