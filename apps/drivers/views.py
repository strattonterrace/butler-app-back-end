"""Driver endpoints — apply, status, available, pending, approve, reject (§11).

Thin views over apps.drivers.services. The `:id` in approve/reject is the
driver's **user id** — the same value `available`/`pending` expose as `id`,
so the frontend passes back exactly what it received.
"""
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin, IsAdminOrOperator, IsDriver

from . import services
from .models import DriverProfile
from .serializers import (
    ApplicationStatusSerializer,
    AvailableDriverSerializer,
    DriverApplySerializer,
    PendingApplicationSerializer,
    RejectDriverSerializer,
)


class DriverApplyView(APIView):
    """POST /api/v1/drivers/apply/ — become a pending driver."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = DriverApplySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        profile = services.apply_as_driver(user=request.user, **s.validated_data)
        return Response(
            ApplicationStatusSerializer(profile).data,
            status=status.HTTP_201_CREATED,
        )


class ApplicationStatusView(APIView):
    """GET /api/v1/drivers/application-status/ — my application state."""
    permission_classes = [IsAuthenticated, IsDriver]

    def get(self, request):
        profile = get_object_or_404(DriverProfile, user=request.user)
        return Response(ApplicationStatusSerializer(profile).data)


class AvailableDriversView(APIView):
    """GET /api/v1/drivers/available/ — approved drivers for assignment."""
    permission_classes = [IsAuthenticated, IsAdminOrOperator]

    def get(self, request):
        drivers = services.available_drivers_for(request.user)
        return Response(AvailableDriverSerializer(drivers, many=True).data)


class PendingDriversView(APIView):
    """GET /api/v1/drivers/pending/ — pending applications (admin)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        applications = services.pending_applications()
        return Response(PendingApplicationSerializer(applications, many=True).data)


class ApproveDriverView(APIView):
    """POST /api/v1/drivers/:id/approve/ — approve an application (admin)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        profile = get_object_or_404(DriverProfile, user_id=pk)
        profile = services.approve_driver(profile=profile, by_admin=request.user)
        return Response(ApplicationStatusSerializer(profile).data)


class RejectDriverView(APIView):
    """POST /api/v1/drivers/:id/reject/ — reject an application (admin)."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        profile = get_object_or_404(DriverProfile, user_id=pk)
        s = RejectDriverSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        profile = services.reject_driver(
            profile=profile, by_admin=request.user, reason=s.validated_data["reason"],
        )
        return Response(ApplicationStatusSerializer(profile).data)
