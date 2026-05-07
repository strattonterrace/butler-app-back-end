"""User routes — mounted at /api/v1/users/"""
from django.urls import path

from .views import CreateOperatorView, MeView, UserDetailView, UserListView

urlpatterns = [
    path("me/", MeView.as_view(), name="users-me"),
    path("", UserListView.as_view(), name="users-list"),
    path("create-operator/", CreateOperatorView.as_view(), name="users-create-operator"),
    path("<uuid:pk>/", UserDetailView.as_view(), name="users-detail"),
]
