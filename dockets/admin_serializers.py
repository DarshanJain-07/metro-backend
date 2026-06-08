from rest_framework import serializers
from .models import RateCard, RateRule, BranchRatePolicy
from core.request_context import get_current_company

class RateCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateCard
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        return data

class RateRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateRule
        fields = '__all__'
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})

        rate_card = data.get('rate_card', getattr(self.instance, 'rate_card', None))
        origin_branch = data.get('origin_branch', getattr(self.instance, 'origin_branch', None))
        destination_branch = data.get('destination_branch', getattr(self.instance, 'destination_branch', None))

        if rate_card and rate_card.company != company:
            raise serializers.ValidationError({"rate_card": "Rate card does not belong to the active company."})
        if origin_branch and origin_branch.company != company:
            raise serializers.ValidationError({"origin_branch": "Origin branch does not belong to the active company."})
        if destination_branch and destination_branch.company != company:
            raise serializers.ValidationError({"destination_branch": "Destination branch does not belong to the active company."})

        return data

class BranchRatePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchRatePolicy
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})

        branch = data.get('branch', getattr(self.instance, 'branch', None))
        if branch and branch.company != company:
            raise serializers.ValidationError({"branch": "Branch does not belong to the active company."})
        if data.get('requires_approval', getattr(self.instance, 'requires_approval', False)):
            raise serializers.ValidationError({"requires_approval": "Rate override approval workflow is not implemented."})
        return data
