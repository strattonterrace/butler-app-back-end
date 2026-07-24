"""Admin API serializers — activity feed shape (metrics/revenue are plain dicts)."""
from rest_framework import serializers

from apps.activity.models import ActivityLog


class ActivitySerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    request_id = serializers.UUIDField(source="target_request_id", read_only=True)

    class Meta:
        model = ActivityLog
        fields = ("id", "type", "message", "actor", "request_id", "metadata", "created_at")
        read_only_fields = fields

    def get_actor(self, obj):
        if obj.actor is None:
            return None
        return {
            "id": obj.actor.id,
            "full_name": obj.actor.full_name,
            "role": obj.actor.role,
        }
