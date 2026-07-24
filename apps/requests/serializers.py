"""ServiceRequest serializers — list/detail/create/transition shapes.

Field names stay snake_case here; the camelCase renderer translates on the
wire (client_name → clientName), matching the mock shapes in src/mock/data.js
so the M3 frontend wire-up is a drop-in.
"""
from rest_framework import serializers

from .models import (
    RequestStatus,
    ScheduledWindow,
    ServiceRequest,
    StatusHistory,
    Urgency,
)


class StatusHistorySerializer(serializers.ModelSerializer):
    changed_by = serializers.SerializerMethodField()

    class Meta:
        model = StatusHistory
        fields = ("id", "from_status", "to_status", "changed_by", "notes", "created_at")

    def get_changed_by(self, obj):
        if obj.changed_by is None:
            return None
        return {
            "id": obj.changed_by.id,
            "full_name": obj.changed_by.full_name,
            "role": obj.changed_by.role,
        }


class ServiceRequestListSerializer(serializers.ModelSerializer):
    """Flat list shape — mirrors MOCK_REQUESTS so dashboards wire straight on."""
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    driver_name = serializers.CharField(
        source="driver.full_name", read_only=True, default=None,
    )

    class Meta:
        model = ServiceRequest
        fields = (
            "id",
            "client",
            "client_name",
            "driver",
            "driver_name",
            "service_type",
            "title",
            "description",
            "pickup_location",
            "dropoff_location",
            "urgency",
            "scheduled_date",
            "scheduled_window",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ServiceRequestDetailSerializer(serializers.ModelSerializer):
    """Full detail: request + parties + audit timeline (§10 detail response)."""
    client = serializers.SerializerMethodField()
    driver = serializers.SerializerMethodField()
    operator = serializers.SerializerMethodField()
    status_history = StatusHistorySerializer(many=True, read_only=True)
    allowed_transitions = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = (
            "id",
            "client",
            "driver",
            "operator",
            "service_type",
            "title",
            "description",
            "pickup_location",
            "dropoff_location",
            "urgency",
            "scheduled_date",
            "scheduled_window",
            "special_instructions",
            "estimated_budget",
            "status",
            "cancel_reason",
            "completion_notes",
            "proof_image_url",
            "assigned_at",
            "started_at",
            "completed_at",
            "closed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            "status_history",
            "allowed_transitions",
        )
        read_only_fields = fields

    def get_client(self, obj):
        return {
            "id": obj.client.id,
            "full_name": obj.client.full_name,
            "email": obj.client.email,
            "phone": obj.client.phone,
        }

    def get_driver(self, obj):
        if obj.driver is None:
            return None
        profile = getattr(obj.driver, "driver_profile", None)
        vehicle = None
        if profile is not None:
            vehicle = f"{profile.vehicle_year} {profile.vehicle_make} {profile.vehicle_model}"
        return {
            "id": obj.driver.id,
            "full_name": obj.driver.full_name,
            "phone": obj.driver.phone,
            "vehicle": vehicle,
        }

    def get_operator(self, obj):
        if obj.operator is None:
            return None
        return {"id": obj.operator.id, "full_name": obj.operator.full_name}

    def get_allowed_transitions(self, obj):
        """UI affordance: which statuses the requesting user could move to."""
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return []
        return obj.allowed_next_statuses(obj.status, request.user.role)


class ServiceRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceRequest
        fields = (
            "service_type",
            "title",
            "description",
            "pickup_location",
            "dropoff_location",
            "urgency",
            "scheduled_date",
            "scheduled_window",
            "special_instructions",
            "estimated_budget",
        )
        extra_kwargs = {
            "special_instructions": {"required": False},
            "estimated_budget": {"required": False},
        }

    def validate(self, attrs):
        # §10: scheduled requests must carry both the date and the window.
        if attrs.get("urgency") == Urgency.SCHEDULED:
            missing = {}
            if not attrs.get("scheduled_date"):
                missing["scheduled_date"] = ["Required when urgency is 'scheduled'."]
            if not attrs.get("scheduled_window"):
                missing["scheduled_window"] = ["Required when urgency is 'scheduled'."]
            if missing:
                raise serializers.ValidationError(missing)
        else:
            # ASAP/today requests can't smuggle in a schedule — normalize out.
            attrs["scheduled_date"] = None
            attrs["scheduled_window"] = None
        return attrs


class StatusTransitionSerializer(serializers.Serializer):
    """Body of PATCH /requests/:id/status/."""
    status = serializers.ChoiceField(choices=RequestStatus.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    driver_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    cancel_reason = serializers.CharField(required=False, allow_blank=True, default="")
    completion_notes = serializers.CharField(required=False, allow_blank=True, default="")
