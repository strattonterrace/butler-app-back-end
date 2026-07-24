"""Admin analytics + user-action endpoints (§12). Admin-only, thin over services."""
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services as account_services
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.accounts.serializers import UserSerializer
from apps.activity.models import ActivityLog

from . import services
from .serializers import ActivitySerializer


class AdminMetricsView(APIView):
    """GET /api/v1/admin/metrics/ — dashboard overview."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        return Response(services.dashboard_metrics())


class AdminRevenueView(APIView):
    """GET /api/v1/admin/revenue/ — chart series + summary."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        return Response(services.revenue_report())


class AdminActivityView(APIView):
    """GET /api/v1/admin/activity/ — recent events (default last 20)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
        except (TypeError, ValueError):
            limit = 20
        events = ActivityLog.objects.select_related("actor")[:limit]
        return Response(ActivitySerializer(events, many=True).data)


class AdminSuspendUserView(APIView):
    """POST /api/v1/admin/users/:id/suspend/ — suspend + side effects."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        # suspend_user raises ValidationError(ADMIN_CANNOT_SELF_SUSPEND) which
        # the global handler turns into a clean 400 envelope.
        account_services.suspend_user(target=target, by_admin=request.user)
        target.refresh_from_db()
        return Response(UserSerializer(target).data)


class AdminReactivateUserView(APIView):
    """POST /api/v1/admin/users/:id/reactivate/ — re-enable an account."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        account_services.reactivate_user(target=target, by_admin=request.user)
        target.refresh_from_db()
        return Response(UserSerializer(target).data)
