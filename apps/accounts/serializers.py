"""Serializers — registration, login (JWT), profile, password reset."""
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Role, Status, User


# ─────────────────────────────────────────────
# User-facing read serializer (returned alongside JWT).
#
# Shape matches the frontend mock in src/store/authStore.js so that wiring
# the real API in M3 is a pure data-source swap, not a refactor of components.
# Field names are snake_case here; the global CamelCaseJSONRenderer flips
# them to camelCase on the wire (full_name → fullName, etc).
# ─────────────────────────────────────────────
class UserSerializer(serializers.ModelSerializer):
    avatar = serializers.CharField(source="avatar_url", default="", read_only=True)
    subscription = serializers.SerializerMethodField()

    # Driver-only fields — flattened onto the user object when role=driver,
    # null otherwise. Matches the mock shape in authStore.js exactly.
    vehicle = serializers.SerializerMethodField()
    availability = serializers.SerializerMethodField()
    approval_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "status",
            "avatar",
            "territory",
            "subscription",
            "vehicle",
            "availability",
            "approval_status",
            "onboarding_completed",
            "preferred_services",
            "created_at",
        )
        read_only_fields = ("id", "email", "role", "status", "created_at")

    # ── Subscription shape:
    # frontend mock: { status, startDate, nextBilling, plan }
    def get_subscription(self, obj):
        sub = getattr(obj, "subscription", None)
        if sub is None:
            return None
        plan = f"${int(sub.plan_amount)}/month" if sub.plan_amount else None
        return {
            "status": sub.status,
            "start_date": sub.current_period_start,   # → startDate
            "next_billing": sub.current_period_end,   # → nextBilling
            "plan": plan,
            "cancel_at_period_end": sub.cancel_at_period_end,  # → cancelAtPeriodEnd
        }

    # ── Driver-only fields ──
    def _profile(self, obj):
        return getattr(obj, "driver_profile", None) if obj.is_driver else None

    def get_vehicle(self, obj):
        profile = self._profile(obj)
        if profile is None:
            return None
        return {
            "make": profile.vehicle_make,
            "model": profile.vehicle_model,
            "year": profile.vehicle_year,
            "plate": profile.license_plate,
        }

    def get_availability(self, obj):
        profile = self._profile(obj)
        if profile is None:
            return None
        return {
            "days": profile.available_days,
            "hours": profile.available_hours,
        }

    def get_approval_status(self, obj):
        profile = self._profile(obj)
        return profile.approval_status if profile else None


# ─────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────
class RegisterSerializer(serializers.Serializer):
    """Field names map to the frontend's RegisterPage form via camelCase
    (confirmPassword on the wire → confirm_password here)."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    full_name = serializers.CharField(min_length=2, max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(attrs["password"])
        # Strip confirm_password from validated_data — the view passes
        # validated_data straight to services.register_user(**kwargs), which
        # doesn't know about confirm_password.
        attrs.pop("confirm_password")
        return attrs


# ─────────────────────────────────────────────
# Custom JWT login — bundles user object in the response
# ─────────────────────────────────────────────
class ButlerTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Email-based login with role-aware response and suspended-account check."""

    username_field = User.USERNAME_FIELD

    def validate(self, attrs):
        # Lowercase the email before delegating to the base validator
        attrs[self.username_field] = attrs[self.username_field].lower().strip()
        data = super().validate(attrs)

        if self.user.status == Status.SUSPENDED:
            raise serializers.ValidationError(
                {"detail": "This account is suspended.", "code": "AUTH_ACCOUNT_SUSPENDED"}
            )

        data["user"] = UserSerializer(self.user, context=self.context).data
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Embed role in the JWT for cheap downstream checks
        token["role"] = user.role
        token["email"] = user.email
        return token


# ─────────────────────────────────────────────
# Logout — blacklist the refresh token
# ─────────────────────────────────────────────
class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def save(self, **kwargs):
        try:
            RefreshToken(self.validated_data["refresh"]).blacklist()
        except Exception as exc:
            raise serializers.ValidationError(
                {"refresh": "Invalid or already-blacklisted token."}
            ) from exc


# ─────────────────────────────────────────────
# Profile update (PATCH /users/me/)
# ─────────────────────────────────────────────
class UserUpdateSerializer(serializers.ModelSerializer):
    avatar = serializers.URLField(source="avatar_url", required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ("full_name", "phone", "avatar")


# ─────────────────────────────────────────────
# Password change (logged-in)
# ─────────────────────────────────────────────
class PasswordChangeSerializer(serializers.Serializer):
    """Field names match changePasswordSchema in src/lib/validations.js."""
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        return attrs


# ─────────────────────────────────────────────
# Account self-delete
# ─────────────────────────────────────────────
class AccountDeleteSerializer(serializers.Serializer):
    """Confirms password before destructive action."""
    password = serializers.CharField(write_only=True)


# ─────────────────────────────────────────────
# Password reset
# ─────────────────────────────────────────────
class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})

        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError):
            raise serializers.ValidationError({"uid": "Invalid reset link."})

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Reset link expired or invalid."})

        validate_password(attrs["password"], user=user)
        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["password"])
        user.save(update_fields=["password"])
        return user


# ─────────────────────────────────────────────
# Driver self-registration
# ─────────────────────────────────────────────
class RegisterDriverSerializer(serializers.Serializer):
    """All fields required to create a driver account + DriverProfile in one step.

    On success the account exists with role=driver, approval_status=pending.
    No JWT is returned — driver goes to a "pending" screen and logs in after approval.
    """
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    full_name = serializers.CharField(min_length=2, max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)

    vehicle_make = serializers.CharField(max_length=50)
    vehicle_model = serializers.CharField(max_length=50)
    vehicle_year = serializers.IntegerField(min_value=1990, max_value=2030)
    license_plate = serializers.CharField(max_length=20)

    available_days = serializers.ListField(
        child=serializers.CharField(max_length=20),
        min_length=1,
    )
    available_hours = serializers.ChoiceField(
        choices=["morning", "afternoon", "evening", "flexible"],
        default="flexible",
    )

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(attrs["password"])
        attrs.pop("confirm_password")
        return attrs


# ─────────────────────────────────────────────
# Admin: create operator
# ─────────────────────────────────────────────
class CreateOperatorSerializer(serializers.Serializer):
    """Wire field is `territoryId` (camelCase parser converts to territory_id),
    which matches services.create_operator(territory_id=...)."""

    email = serializers.EmailField()
    full_name = serializers.CharField(min_length=2, max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    territory_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value


# ─────────────────────────────────────────────
# Admin: update any user (limited field set)
# ─────────────────────────────────────────────
class AdminUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("full_name", "phone", "role", "status", "territory")


# Helper used by the password-reset view to build the redirect URL
def build_password_reset_uid_token(user):
    return (
        urlsafe_base64_encode(force_bytes(user.pk)),
        default_token_generator.make_token(user),
    )


class OnboardingSerializer(serializers.Serializer):
    """Body of POST /auth/onboarding/ — the client signup wizard's final step."""
    territory_id = serializers.UUIDField()
    address = serializers.CharField(required=False, allow_blank=True, default="")
    preferred_services = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
    )
