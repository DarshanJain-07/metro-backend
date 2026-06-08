from rest_framework import serializers

from core.request_context import get_current_company
from .models import OfficeRatePolicy, RateCard, RateRule


class RateCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateCard
        fields = ["id", "company", "name", "is_default", "effective_from", "effective_to", "is_active", "created_at", "updated_at"]
        read_only_fields = ["company"]


class RateRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateRule
        fields = [
            "id",
            "rate_card",
            "origin_city",
            "destination_city",
            "origin_office",
            "destination_office",
            "basis",
            "rate_type",
            "rate",
            "min_charge",
            "delivery_charge",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def validate(self, data):
        company = get_current_company()
        rate_card = data.get("rate_card", getattr(self.instance, "rate_card", None))
        origin_office = data.get("origin_office", getattr(self.instance, "origin_office", None))
        destination_office = data.get("destination_office", getattr(self.instance, "destination_office", None))
        if rate_card and rate_card.company != company:
            raise serializers.ValidationError({"rate_card": "Rate card does not belong to the active company."})
        if origin_office and origin_office.company != company:
            raise serializers.ValidationError({"origin_office": "Origin office does not belong to the active company."})
        if destination_office and destination_office.company != company:
            raise serializers.ValidationError({"destination_office": "Destination office does not belong to the active company."})
        return data


class OfficeRatePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = OfficeRatePolicy
        fields = ["id", "company", "office", "can_override_rate", "max_discount_percent", "requires_approval", "created_at", "updated_at"]
        read_only_fields = ["company"]

    def validate(self, data):
        company = get_current_company()
        office = data.get("office", getattr(self.instance, "office", None))
        if office and office.company != company:
            raise serializers.ValidationError({"office": "Office does not belong to the active company."})
        return data
