"""Auth + user management views — thin wrappers over services.

Pattern: parse → delegate to services.py → serialize. Business logic
(side effects, multi-step orchestration) lives in services. This keeps
view code small and predictable, and means M3 endpoints follow the same
shape — no view-level rot.
"""
from django.contrib.auth import user_logged_in
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import services
from .models import User
from .permissions import IsAdmin
from .serializers import (
    AdminUserUpdateSerializer,
    AccountDeleteSerializer,
    ButlerTokenObtainPairSerializer,
    CreateOperatorSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    UserSerializer,
    UserUpdateSerializer,
)


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────
class RegisterView(APIView):
    """POST /api/v1/auth/register/ — create a client account + return JWT."""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = services.register_user(**s.validated_data)

        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["email"] = user.email

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — JWT pair + last_login update."""
    serializer_class = ButlerTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            # simplejwt doesn't fire the user_logged_in signal — do it ourselves
            # so last_login gets updated by Django's update_last_login receiver.
            user = User.objects.get(email=request.data.get("email", "").lower().strip())
            user_logged_in.send(sender=user.__class__, request=request, user=user)
        return response


class TokenRefreshThrottledView(TokenRefreshView):
    """POST /api/v1/auth/token/refresh/"""
    permission_classes = [AllowAny]


class LogoutView(APIView):
    """POST /api/v1/auth/logout/ — blacklist refresh token."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = LogoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    """POST /api/v1/auth/password-reset/ — timing-safe."""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        s = PasswordResetRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.request_password_reset(email=s.validated_data["email"])
        return Response(
            {"detail": "If an account exists for that email, a reset link has been sent."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """POST /api/v1/auth/password-reset/confirm/"""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        s = PasswordResetConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.confirm_password_reset(
            uid=s.validated_data["uid"],
            token=s.validated_data["token"],
            new_password=s.validated_data["password"],
        )
        return Response({"detail": "Password has been reset."}, status=status.HTTP_200_OK)


class PasswordChangeView(APIView):
    """POST /api/v1/auth/password-change/ — logged-in change.

    Distinct from password-reset (which uses a one-time email token).
    Requires the user to confirm their current password.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = PasswordChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.change_password(
            user=request.user,
            current_password=s.validated_data["current_password"],
            new_password=s.validated_data["new_password"],
        )
        return Response({"detail": "Password updated."}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────
class MeView(generics.RetrieveUpdateAPIView):
    """GET / PATCH / DELETE /api/v1/users/me/

    DELETE is a soft-delete: account flips to suspended + Stripe sub
    cancels at period end (M2 wires the Stripe call).
    """
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method == "GET":
            return UserSerializer
        return UserUpdateSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(UserSerializer(self.get_object()).data)

    def delete(self, request, *args, **kwargs):
        s = AccountDeleteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        services.delete_account(user=request.user, password=s.validated_data["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListView(generics.ListAPIView):
    """GET /api/v1/users/ — admin only."""
    permission_classes = [IsAdmin]
    serializer_class = UserSerializer
    queryset = User.objects.all().order_by("-created_at")
    filterset_fields = ("role", "status", "territory")
    search_fields = ("full_name", "email")
    ordering_fields = ("created_at", "full_name")


class UserDetailView(generics.RetrieveUpdateAPIView):
    """GET / PATCH /api/v1/users/:id/ — admin only."""
    permission_classes = [IsAdmin]
    queryset = User.objects.all()

    def get_serializer_class(self):
        if self.request.method == "GET":
            return UserSerializer
        return AdminUserUpdateSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        # Block admins from suspending themselves
        if instance == request.user and request.data.get("status") == "suspended":
            return Response(
                {
                    "status": "error",
                    "code": "ADMIN_CANNOT_SELF_SUSPEND",
                    "message": "An admin cannot suspend their own account.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        super().update(request, *args, **kwargs)
        return Response(UserSerializer(self.get_object()).data)


class CreateOperatorView(APIView):
    """POST /api/v1/users/create-operator/ — admin only."""
    permission_classes = [IsAdmin]

    def post(self, request):
        s = CreateOperatorSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = services.create_operator(by_admin=request.user, **s.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
