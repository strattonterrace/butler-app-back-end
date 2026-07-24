"""Request lifecycle views — thin wrappers over services (§10).

Visibility is never re-derived here: every queryset starts from
`ServiceRequest.objects.visible_to(user)`, so a request another role
shouldn't see 404s instead of leaking through an object check.
"""
from rest_framework import generics, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsActiveSubscriber, IsClient

from . import services
from .models import ServiceRequest
from .serializers import (
    ServiceRequestCreateSerializer,
    ServiceRequestDetailSerializer,
    ServiceRequestListSerializer,
    StatusHistorySerializer,
    StatusTransitionSerializer,
)
from .services import TransitionError


def _visible_requests(user):
    return (
        ServiceRequest.objects.visible_to(user)
        .select_related("client", "driver", "driver__driver_profile", "operator")
    )


class RequestListCreateView(generics.ListCreateAPIView):
    """GET /api/v1/requests/ — role-aware list.
    POST /api/v1/requests/ — client submits a new request (active sub only).
    """
    filterset_fields = ("status", "service_type", "urgency", "client")
    search_fields = ("title", "description")
    ordering_fields = ("created_at", "urgency")

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsClient(), IsActiveSubscriber()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return _visible_requests(self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ServiceRequestCreateSerializer
        return ServiceRequestListSerializer

    def create(self, request, *args, **kwargs):
        s = ServiceRequestCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        service_request = services.create_request(
            client=request.user, **s.validated_data,
        )
        return Response(
            ServiceRequestDetailSerializer(
                service_request, context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class RequestDetailView(generics.RetrieveAPIView):
    """GET /api/v1/requests/:id/ — full detail + parties + timeline."""
    serializer_class = ServiceRequestDetailSerializer

    def get_queryset(self):
        return _visible_requests(self.request.user).prefetch_related(
            "status_history__changed_by",
        )


class RequestStatusView(APIView):
    """PATCH /api/v1/requests/:id/status/ — transition the lifecycle."""

    def patch(self, request, pk):
        service_request = get_object_or_404(
            _visible_requests(request.user), pk=pk,
        )
        s = StatusTransitionSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            service_request = services.transition_request(
                service_request,
                new_status=s.validated_data["status"],
                by_user=request.user,
                driver_id=s.validated_data.get("driver_id"),
                notes=s.validated_data.get("notes", ""),
                cancel_reason=s.validated_data.get("cancel_reason", ""),
                completion_notes=s.validated_data.get("completion_notes", ""),
            )
        except TransitionError as exc:
            return Response(
                {"status": "error", "message": exc.message, "code": exc.code},
                status=exc.http_status,
            )

        return Response(
            ServiceRequestDetailSerializer(
                service_request, context={"request": request},
            ).data,
        )


class RequestHistoryView(APIView):
    """GET /api/v1/requests/:id/history/ — audit timeline as a flat array."""

    def get(self, request, pk):
        service_request = get_object_or_404(
            _visible_requests(request.user), pk=pk,
        )
        history = service_request.status_history.select_related("changed_by")
        return Response(StatusHistorySerializer(history, many=True).data)


class RequestStatsView(APIView):
    """GET /api/v1/requests/stats/ — role-shaped dashboard counters."""

    def get(self, request):
        return Response(services.request_stats(request.user))
