"""Auth routes — mounted at /api/v1/auth/"""
from django.urls import path

from .views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RegisterDriverView,
    RegisterView,
    TokenRefreshThrottledView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("register/driver/", RegisterDriverView.as_view(), name="auth-register-driver"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("token/refresh/", TokenRefreshThrottledView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password-change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
]
