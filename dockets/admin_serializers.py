from rest_framework import serializers
from .models import RateCard, RateRule, BranchRatePolicy

class RateCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateCard
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']

class RateRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateRule
        fields = '__all__'
        read_only_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']

class BranchRatePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchRatePolicy
        fields = '__all__'
        read_only_fields = ['company', 'created_by', 'updated_by', 'created_at', 'updated_at']
