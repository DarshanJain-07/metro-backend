from django.contrib.auth import get_user_model
import django.contrib.auth.password_validation as validators
from django.core.exceptions import ValidationError
from rest_framework import serializers

from core.models import (
    CompanyRolePermissionOverride,
    CompanyOffice,
    PermissionCatalog,
    PermissionScope,
    Role,
    UserMembership,
)
from core.policies import effective_membership_grants, effective_permissions_for_user, role_template_revision, template_role_grants
from core.request_context import get_current_company

User = get_user_model()


class UserMembershipSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source="company.name")
    office_name = serializers.ReadOnlyField(source="office.name", default=None)
    branch = serializers.PrimaryKeyRelatedField(
        source="office",
        queryset=CompanyOffice.objects.all(),
        required=False,
        allow_null=True,
    )
    branch_name = serializers.ReadOnlyField(source="office.name", default=None)
    permissions = serializers.SerializerMethodField()
    scoped_permissions = serializers.SerializerMethodField()

    class Meta:
        model = UserMembership
        fields = (
            "id",
            "user",
            "company",
            "company_name",
            "office",
            "office_name",
            "branch",
            "branch_name",
            "role",
            "permissions",
            "scoped_permissions",
        )
        read_only_fields = ("company",)
        extra_kwargs = {"user": {"required": False}}

    def get_permissions(self, obj):
        return sorted(effective_membership_grants(obj).keys())

    def get_scoped_permissions(self, obj):
        return [
            {"code": code, "scope": scope}
            for code, scope in sorted(effective_membership_grants(obj).items())
        ]

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        office = data.get("office", getattr(self.instance, "office", None))
        role = data.get("role", getattr(self.instance, "role", None))
        office_roles = {Role.BRANCH_ADMIN, Role.BOOKING_USER, Role.DELIVERY_USER, Role.ACCOUNTANT, Role.VIEWER}
        if role in office_roles and not office:
            raise serializers.ValidationError({"office": "Office is required for this role."})
        if role in (Role.PLATFORM_ADMIN, Role.SUPER_ADMIN) and office:
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
    permissions = serializers.SerializerMethodField()
    scoped_permissions = serializers.SerializerMethodField()

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
            "permissions",
            "scoped_permissions",
        )
        read_only_fields = (
            "id",
            "is_superuser",
            "is_owner",
            "company_name",
            "office_name",
            "memberships",
            "permissions",
            "scoped_permissions",
        )

    def get_permissions(self, obj):
        if obj.is_superuser:
            return ["*"]
        return sorted(effective_permissions_for_user(obj).keys())

    def get_scoped_permissions(self, obj):
        return [
            {"code": code, "scope": scope}
            for code, scope in sorted(effective_permissions_for_user(obj).items())
        ]

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
                raise serializers.ValidationError({"membership_inputs": "Super admins cannot create platform admins."})
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


class PermissionCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermissionCatalog
        fields = ("id", "code", "name", "group", "description", "is_active")


class RoleTemplateSummarySerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)
    name = serializers.CharField()
    revision = serializers.IntegerField()
    default_permissions = serializers.ListField()


class CompanyRolePermissionOverrideSerializer(serializers.ModelSerializer):
    permission_code = serializers.SlugRelatedField(
        source="permission",
        slug_field="code",
        queryset=PermissionCatalog.objects.filter(is_active=True),
        write_only=True,
    )
    code = serializers.ReadOnlyField(source="permission.code")
    name = serializers.ReadOnlyField(source="permission.name")
    group = serializers.ReadOnlyField(source="permission.group")

    class Meta:
        model = CompanyRolePermissionOverride
        fields = (
            "id",
            "role",
            "permission_code",
            "code",
            "name",
            "group",
            "enabled",
            "scope",
            "based_on_template_revision",
        )
        read_only_fields = ("id", "code", "name", "group")

    def validate_role(self, value):
        if value == Role.PLATFORM_ADMIN:
            raise serializers.ValidationError("Platform admin permissions are managed globally.")
        return value

    def validate_scope(self, value):
        if value not in PermissionScope.values:
            raise serializers.ValidationError("Invalid scope.")
        return value

    def create(self, validated_data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        validated_data["company"] = company
        validated_data.setdefault("based_on_template_revision", role_template_revision(validated_data["role"]))
        obj, _ = CompanyRolePermissionOverride.objects.update_or_create(
            company=company,
            role=validated_data["role"],
            permission=validated_data["permission"],
            defaults={
                "enabled": validated_data.get("enabled", True),
                "scope": validated_data.get("scope", PermissionScope.BRANCH),
                "based_on_template_revision": validated_data["based_on_template_revision"],
            },
        )
        return obj


def role_template_payload(role):
    grants = template_role_grants(role)
    return {
        "role": role,
        "name": Role(role).label,
        "revision": role_template_revision(role),
        "default_permissions": [
            {"code": code, "scope": scope}
            for code, scope in sorted(grants.items())
        ],
    }
