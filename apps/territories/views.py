"""Public territory endpoints powering the onboarding location gate."""
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Territory, TerritoryStatus
from .serializers import ServedTerritorySerializer, WaitlistEntrySerializer


class ServedAreasView(generics.ListAPIView):
    """GET /api/v1/territories/served/ — active territories, for display."""
    permission_classes = [AllowAny]
    pagination_class = None
    serializer_class = ServedTerritorySerializer

    def get_queryset(self):
        return Territory.objects.filter(status=TerritoryStatus.ACTIVE).order_by("name")


class TerritoryCheckView(APIView):
    """GET /api/v1/territories/check/?zip=92618 — is this ZIP served?

    Public: the gate runs before an account exists.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        zip_code = (request.query_params.get("zip") or "").strip()
        if not zip_code:
            return Response(
                {"status": "error", "code": "ZIP_REQUIRED",
                 "message": "A ZIP code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for territory in Territory.objects.filter(status=TerritoryStatus.ACTIVE):
            if territory.serves_zip(zip_code):
                return Response({
                    "served": True,
                    "territory": ServedTerritorySerializer(territory).data,
                })
        return Response({"served": False, "territory": None})


class WaitlistJoinView(generics.CreateAPIView):
    """POST /api/v1/territories/waitlist/ — capture out-of-area demand."""
    permission_classes = [AllowAny]
    serializer_class = WaitlistEntrySerializer
