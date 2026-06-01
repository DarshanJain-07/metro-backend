from rest_framework import serializers
from django.contrib.auth import get_user_model
import django.contrib.auth.password_validation as validators
from django.core.exceptions import ValidationError

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source='company.name', default=None)
    branch_name = serializers.ReadOnlyField(source='branch.name', default=None)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'company_name', 'branch_name', 'is_owner')

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        # Enforce Django's password complexity rules
        try:
            validators.validate_password(value)
        except ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value
        
    def validate(self, data):
        if data['old_password'] == data['new_password']:
            raise serializers.ValidationError({"new_password": "New password cannot be the same as the old password."})
        return data
