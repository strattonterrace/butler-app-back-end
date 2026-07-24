"""Driver serializers — application, status, and assignment-list shapes."""
from rest_framework import serializers

from .models import AvailableHours, DriverProfile


class DriverApplySerializer(serializers.Serializer):
    """Body of POST /drivers/apply/."""
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    vehicle_make = serializers.CharField(max_length=50)
    vehicle_model = serializers.CharField(max_length=50)
    vehicle_year = serializers.IntegerField(min_value=1980, max_value=2100)
    license_plate = serializers.CharField(max_length=20)
    available_days = serializers.ListField(
        child=serializers.CharField(), allow_empty=False,
    )
    available_hours = serializers.ChoiceField(
        choices=AvailableHours.choices, default=AvailableHours.FLEXIBLE,
    )


class ApplicationStatusSerializer(serializers.ModelSerializer):
    applied_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = DriverProfile
        fields = ("approval_status", "rejection_reason", "applied_at")
        read_only_fields = fields


class AvailableDriverSerializer(serializers.ModelSerializer):
    """Assignment dropdown row — approved driver + live workload."""
    id = serializers.UUIDField(source="user.id", read_only=True)
    name = serializers.CharField(source="user.full_name", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    vehicle = serializers.SerializerMethodField()
    current_task_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DriverProfile
        fields = (
            "id",
            "name",
            "phone",
            "vehicle",
            "available_days",
            "available_hours",
            "rating",
            "current_task_count",
        )

    def get_vehicle(self, obj):
        return f"{obj.vehicle_year} {obj.vehicle_make} {obj.vehicle_model}"


class PendingApplicationSerializer(serializers.ModelSerializer):
    """Admin review row for a pending application."""
    id = serializers.UUIDField(source="user.id", read_only=True)
    profile_id = serializers.UUIDField(source="id", read_only=True)
    name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    vehicle = serializers.SerializerMethodField()
    applied_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = DriverProfile
        fields = (
            "id",
            "profile_id",
            "name",
            "email",
            "phone",
            "vehicle",
            "license_plate",
            "available_days",
            "available_hours",
            "approval_status",
            "applied_at",
        )
        read_only_fields = fields

    def get_vehicle(self, obj):
        return f"{obj.vehicle_year} {obj.vehicle_make} {obj.vehicle_model}"


class RejectDriverSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
