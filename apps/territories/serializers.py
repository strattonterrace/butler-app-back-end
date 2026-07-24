"""Territory + waitlist serializers (public onboarding surface)."""
from rest_framework import serializers

from .models import Territory, WaitlistEntry


class ServedTerritorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Territory
        fields = ("id", "name")
        read_only_fields = fields


class WaitlistEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WaitlistEntry
        fields = ("id", "email", "zip_code", "full_name", "note", "created_at")
        read_only_fields = ("id", "created_at")

    def create(self, validated_data):
        # Idempotent — re-joining with the same email+zip is a no-op, not a 500.
        entry, _ = WaitlistEntry.objects.get_or_create(
            email=validated_data["email"].lower().strip(),
            zip_code=validated_data.get("zip_code", "").strip(),
            defaults={
                "full_name": validated_data.get("full_name", ""),
                "note": validated_data.get("note", ""),
            },
        )
        return entry
