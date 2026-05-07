"""Custom DRF permission classes — role-based + subscription/approval gates."""
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Role


def _has_role(request, *roles):
    user = request.user
    return bool(user and user.is_authenticated and user.role in roles)


class IsClient(BasePermission):
    message = "Client role required."

    def has_permission(self, request, view):
        return _has_role(request, Role.CLIENT)


class IsOperator(BasePermission):
    message = "Operator role required."

    def has_permission(self, request, view):
        return _has_role(request, Role.OPERATOR)


class IsDriver(BasePermission):
    message = "Driver role required."

    def has_permission(self, request, view):
        return _has_role(request, Role.DRIVER)


class IsAdmin(BasePermission):
    message = "Admin role required."

    def has_permission(self, request, view):
        return _has_role(request, Role.ADMIN)


class IsAdminOrOperator(BasePermission):
    """Admin is a super-operator — admins pass any operator-gated check."""
    message = "Operator or admin role required."

    def has_permission(self, request, view):
        return _has_role(request, Role.OPERATOR, Role.ADMIN)


class IsActiveSubscriber(BasePermission):
    """Fail-closed gate — only clients with status='active' on their
    Subscription pass.

    Architecture: every client gets a Subscription row at registration
    (see apps.accounts.signals._ensure_subscription_stub) with status='inactive'.
    Stripe webhooks (M2) flip it to 'active' on `checkout.session.completed`.

    Non-clients (operator/driver/admin) bypass the gate — they don't pay
    a subscription.

    Note: we deliberately query the database directly rather than reading
    `user.subscription`. Django warms the reverse-OneToOne cache when the
    Subscription is created in the same request cycle, which produces stale
    reads after a webhook flips the status. Security gates can't rely on
    cached values.
    """
    message = "Active subscription required."
    code = "SUB_NOT_ACTIVE"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role != Role.CLIENT:
            return True

        from apps.subscriptions.models import Subscription, SubscriptionStatus
        return Subscription.objects.filter(
            user=user, status=SubscriptionStatus.ACTIVE,
        ).exists()


class IsApprovedDriver(BasePermission):
    message = "Approved driver status required."
    code = "DRV_NOT_APPROVED"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.role == Role.DRIVER):
            return False
        profile = getattr(user, "driver_profile", None)
        return bool(profile and profile.approval_status == "approved")


class IsOwnerOrAdmin(BasePermission):
    """Object-level: allow access if requester owns the object or is admin.

    Expects the view to expose either obj.user or obj.client / obj.driver
    pointing at a User instance.
    """
    message = "You don't have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role == Role.ADMIN:
            return True
        owner = (
            getattr(obj, "user", None)
            or getattr(obj, "client", None)
            or getattr(obj, "driver", None)
        )
        return owner == user


class IsTerritoryScoped(BasePermission):
    """Object-level: operator/driver only see objects in their own territory.
    Admin always passes; clients pass for objects they own.

    Resolves the object's territory via, in order:
      1. obj.territory_id  (DriverProfile, Territory)
      2. obj.client.territory_id  (ServiceRequest, etc.)
      3. None → fail closed for non-admins
    """
    message = "This resource belongs to a different territory."
    code = "TERRITORY_MISMATCH"

    @staticmethod
    def _resolve_territory_id(obj):
        # Direct territory FK
        territory_id = getattr(obj, "territory_id", None)
        if territory_id is not None:
            return territory_id
        # Indirect via client
        client = getattr(obj, "client", None)
        if client is not None:
            return getattr(client, "territory_id", None)
        return None

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role == Role.ADMIN:
            return True

        territory_id = self._resolve_territory_id(obj)

        if user.role == Role.OPERATOR:
            # Fail closed: no territory on either side → deny
            if territory_id is None or user.territory_id is None:
                return False
            return territory_id == user.territory_id

        if user.role == Role.DRIVER:
            profile = getattr(user, "driver_profile", None)
            if profile is None or profile.territory_id is None:
                return False
            if territory_id is None:
                return False
            return territory_id == profile.territory_id

        # Clients fall through — IsRequestParticipant handles them
        return True


class IsRequestParticipant(BasePermission):
    """Object-level permission for ServiceRequest objects.

    Allowed if the requesting user is one of:
      - admin (global)
      - operator whose territory matches the request's client.territory
      - driver assigned to the request (or unassigned reviewed request in their
        territory if the view is the "available orders" endpoint — handled separately)
      - client who submitted the request

    For non-ServiceRequest objects, falls through (returns True) so this
    permission can be safely combined with others.
    """
    message = "You are not a participant on this request."

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        # Only enforce for objects shaped like a ServiceRequest
        if not (hasattr(obj, "client_id") and hasattr(obj, "driver_id")):
            return True

        if user.role == Role.ADMIN:
            return True
        if user.role == Role.CLIENT:
            return obj.client_id == user.id
        if user.role == Role.DRIVER:
            return obj.driver_id == user.id
        if user.role == Role.OPERATOR:
            if user.territory_id is None:
                return False
            client_territory_id = getattr(obj.client, "territory_id", None)
            if client_territory_id is None:
                return False
            return client_territory_id == user.territory_id
        return False


class ReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS
