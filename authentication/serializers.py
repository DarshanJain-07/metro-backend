from django.contrib.auth import get_user_model
import django.contrib.auth.password_validation as validators
from django.core.exceptions import ValidationError
from rest_framework import serializers

from core.models import Role, UserMembership
from core.request_context import get_current_company

User = get_user_model()


class UserMembershipSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source="company.name")
    office_name = serializers.ReadOnlyField(source="office.name", default=None)

    class Meta:
        model = UserMembership
        fields = ("id", "user", "company", "company_name", "office", "office_name", "role")
        read_only_fields = ("company",)
        extra_kwargs = {"user": {"required": False}}

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        office = data.get("office", getattr(self.instance, "office", None))
        role = data.get("role", getattr(self.instance, "role", None))
        office_roles = {Role.OFFICE_ADMIN, Role.BOOKING_USER, Role.DELIVERY_USER, Role.ACCOUNTANT, Role.VIEWER}
        if role in office_roles and not office:
            raise serializers.ValidationError({"office": "Office is required for this role."})
        if role in (Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN) and office:
            raise serializers.ValidationError({"office": "Company-level roles must not include an office."})
        if office and office.company != company:
            raise serializers.ValidationError({"office": "Office does not belong to the active company."})
        return data


class UserSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source="company.name", default=None)
    office_name = serializers.ReadOnlyField(source="office.name", default=None)
    memberships = UserMembershipSerializer(many=True, read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    membership_inputs = UserMembershipSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "company_name",
            "office_name",
            "is_superuser",
            "is_owner",
            "memberships",
            "membership_inputs",
        )
        read_only_fields = ("id", "is_superuser", "is_owner", "company_name", "office_name", "memberships")

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        memberships = data.get("membership_inputs") or []
        if not self.instance and not memberships:
            raise serializers.ValidationError({"membership_inputs": "At least one membership is required."})
        for membership in memberships:
            office = membership.get("office")
            role = membership.get("role")
            if office and office.company != company:
                raise serializers.ValidationError({"membership_inputs": "Membership office is outside the active company."})
            if role == Role.PLATFORM_ADMIN:
                raise serializers.ValidationError({"membership_inputs": "Client admins cannot create platform admins."})
        return data

    def create(self, validated_data):
        memberships = validated_data.pop("membership_inputs", [])
        password = validated_data.pop("password", None)
        company = get_current_company()
        user = User(**validated_data)
        user.company = company
        user.office = next((membership.get("office") for membership in memberships if membership.get("office")), None)
        if password:
            try:
                validators.validate_password(password, user)
            except ValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)})
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        for membership in memberships:
            UserMembership.objects.create(
                user=user,
                company=company,
                office=membership.get("office"),
                role=membership["role"],
            )
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        try:
            validators.validate_password(value)
        except ValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, data):
        if data["old_password"] == data["new_password"]:
            raise serializers.ValidationError({"new_password": "New password cannot be the same as the old password."})
        return data
