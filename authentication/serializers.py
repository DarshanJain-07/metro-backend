from rest_framework import serializers
from django.contrib.auth import get_user_model
import django.contrib.auth.password_validation as validators
from django.core.exceptions import ValidationError
from core.models import Branch, Role, UserMembership
from core.request_context import get_current_company

User = get_user_model()

class UserMembershipSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source='company.name')
    branch_name = serializers.ReadOnlyField(source='branch.name', default=None)

    class Meta:
        model = UserMembership
        fields = ('id', 'user', 'company', 'company_name', 'branch', 'branch_name', 'role')
        read_only_fields = ('company',)
        extra_kwargs = {'user': {'required': False}}

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})

        branch = data.get('branch', getattr(self.instance, 'branch', None))
        role = data.get('role', getattr(self.instance, 'role', None))
        branch_roles = {
            Role.BRANCH_ADMIN,
            Role.BOOKING_USER,
            Role.DELIVERY_USER,
            Role.ACCOUNTANT,
            Role.VIEWER,
        }

        if role in branch_roles and not branch:
            raise serializers.ValidationError({"branch": "Branch is required for this role."})
        if role in (Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN) and branch:
            raise serializers.ValidationError({"branch": "Company-level roles must not include a branch."})
        if branch and branch.company != company:
            raise serializers.ValidationError({"branch": "Branch does not belong to the active company."})

        user = data.get('user', getattr(self.instance, 'user', None))
        if user and user.pk:
            user_company_ids = set(UserMembership.unscoped_objects.filter(
                user=user,
                is_active=True,
            ).values_list('company_id', flat=True))
            if user_company_ids and company.id not in user_company_ids:
                raise serializers.ValidationError({"user": "User is outside the active company."})

        return data

class UserSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source='company.name', default=None)
    branch_name = serializers.ReadOnlyField(source='branch.name', default=None)
    memberships = UserMembershipSerializer(many=True, read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    membership_inputs = UserMembershipSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 
            'password', 'company_name', 'branch_name', 'is_superuser', 'is_owner',
            'memberships', 'membership_inputs',
        )
        read_only_fields = ('id', 'is_superuser', 'is_owner', 'company_name', 'branch_name', 'memberships')

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})

        memberships = data.get('membership_inputs') or []
        if not self.instance and not memberships:
            raise serializers.ValidationError({"membership_inputs": "At least one membership is required."})
        for membership in memberships:
            branch = membership.get('branch')
            role = membership.get('role')
            if branch and branch.company != company:
                raise serializers.ValidationError({"membership_inputs": "Membership branch is outside the active company."})
            if role == Role.PLATFORM_ADMIN:
                raise serializers.ValidationError({"membership_inputs": "Client admins cannot create platform admins."})
        return data

    def create(self, validated_data):
        memberships = validated_data.pop('membership_inputs', [])
        password = validated_data.pop('password', None)
        company = get_current_company()

        user = User(**validated_data)
        user.company = company
        first_branch = next((membership.get('branch') for membership in memberships if membership.get('branch')), None)
        user.branch = first_branch
        if password:
            validators.validate_password(password, user)
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()

        for membership in memberships:
            UserMembership.objects.create(
                user=user,
                company=company,
                branch=membership.get('branch'),
                role=membership['role'],
            )

        return user


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
