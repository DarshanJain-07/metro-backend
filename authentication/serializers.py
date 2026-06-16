from django.contrib.auth import get_user_model
import django.contrib.auth.password_validation as validators
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import serializers

from core.models import (
    CompanyRolePermissionOverride,
    CompanyOffice,
    OfficeStatus,
    PermissionCatalog,
    PermissionScope,
    Role,
    RoleDefinition,
    UserMembership,
)
from core.policies import (
    active_role_definitions,
    effective_membership_grants,
    effective_permissions_for_user,
    role_definition,
    role_requires_office,
    role_template_revision,
    template_role_grants,
)
from core.request_context import get_current_company

User = get_user_model()


def assignable_user_offices(company):
    return CompanyOffice.unscoped_objects.filter(
        company=company,
        is_active=True,
        status=OfficeStatus.ACTIVE,
        office_type__in=[CompanyOffice.OfficeType.OWN, CompanyOffice.OfficeType.MANUAL],
    ).filter(
        Q(global_office__isnull=True)
        | Q(global_office__owner_company__isnull=True)
        | Q(global_office__owner_company=company)
    ).order_by("name")


def is_assignable_user_office(office, company):
    if not office:
        return True
    return assignable_user_offices(company).filter(pk=office.pk).exists()


def validate_and_set_password(user, password):
    try:
        validators.validate_password(password, user)
    except ValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)})
    user.set_password(password)


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
        if role and not role_definition(role):
            raise serializers.ValidationError({"role": "Invalid role."})
        if role and role_requires_office(role) and not office:
            raise serializers.ValidationError({"office": "Office is required for this role."})
        if role and not role_requires_office(role) and office:
            raise serializers.ValidationError({"office": "Company-level roles must not include an office."})
        if office and not is_assignable_user_office(office, company):
            raise serializers.ValidationError({"office": "Office cannot be assigned to users for the active company."})
        return data


class UserSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source="company.name", default=None)
    branch = serializers.PrimaryKeyRelatedField(
        source="office",
        queryset=CompanyOffice.unscoped_objects.all(),
        required=False,
        allow_null=True,
    )
    branch_name = serializers.ReadOnlyField(source="office.name", default=None)
    office_name = serializers.ReadOnlyField(source="office.name", default=None)
    memberships = UserMembershipSerializer(many=True, read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    membership_inputs = UserMembershipSerializer(many=True, write_only=True, required=False)
    role = serializers.CharField(required=False, allow_blank=True)
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
            "branch",
            "branch_name",
            "office_name",
            "role",
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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        company = get_current_company()
        memberships = instance.memberships.all()
        membership = next(
            (
                item
                for item in memberships
                if item.is_active and (not company or item.company_id == company.id)
            ),
            None,
        )
        data["role"] = membership.role if membership else None
        return data

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        memberships = data.get("membership_inputs") or []
        office = data.get("office", getattr(self.instance, "office", None))
        role = data.get("role")
        current_membership = None
        if not role and self.instance:
            current_membership = self.instance.memberships.filter(company=company, is_active=True).first()
            role = current_membership.role if current_membership else None
            office = office or (current_membership.office if current_membership else None)
        if not self.instance and not memberships and not role:
            raise serializers.ValidationError({"membership_inputs": "At least one membership is required."})
        if role == "":
            raise serializers.ValidationError({"role": "Role is required."})
        if role and not role_definition(role):
            raise serializers.ValidationError({"role": "Invalid role."})
        if role and role_requires_office(role) and not office:
            raise serializers.ValidationError({"branch": "Default branch is required for this role."})
        if role and not role_requires_office(role) and office:
            raise serializers.ValidationError({"branch": "Company-level roles must not have a default branch."})
        if office and not is_assignable_user_office(office, company):
            raise serializers.ValidationError({"branch": "This branch cannot be assigned to users for the active company."})
        for membership in memberships:
            membership_office = membership.get("office")
            membership_role = membership.get("role")
            if membership_role and not role_definition(membership_role):
                raise serializers.ValidationError({"membership_inputs": "Invalid membership role."})
            if membership_role and role_requires_office(membership_role) and not membership_office:
                raise serializers.ValidationError({"membership_inputs": "Membership office is required for this role."})
            if membership_role and not role_requires_office(membership_role) and membership_office:
                raise serializers.ValidationError({"membership_inputs": "Company-level roles must not include an office."})
            if membership_office and not is_assignable_user_office(membership_office, company):
                raise serializers.ValidationError({"membership_inputs": "Membership office cannot be assigned to users."})
        return data

    def create(self, validated_data):
        memberships = validated_data.pop("membership_inputs", [])
        password = validated_data.pop("password", None)
        role = validated_data.pop("role", None)
        office = validated_data.pop("office", None)
        company = get_current_company()
        if not memberships and role:
            memberships = [{"office": office, "role": role}]
        user = User(**validated_data)
        user.company = company
        user.office = office or next((membership.get("office") for membership in memberships if membership.get("office")), None)
        if password:
            validate_and_set_password(user, password)
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

    def update(self, instance, validated_data):
        memberships = validated_data.pop("membership_inputs", None)
        password = validated_data.pop("password", None)
        role = validated_data.pop("role", None)
        office_provided = "office" in validated_data
        office = validated_data.pop("office", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if office_provided:
            instance.office = office
        if password:
            validate_and_set_password(instance, password)
        instance.save()
        company = get_current_company()
        if memberships is not None:
            instance.memberships.filter(company=company).update(is_active=False)
            for membership in memberships:
                UserMembership.objects.update_or_create(
                    user=instance,
                    company=company,
                    office=membership.get("office"),
                    role=membership["role"],
                    defaults={"is_active": True},
                )
        elif role is not None or office_provided:
            current_membership = instance.memberships.filter(company=company, is_active=True).first()
            next_role = role or (current_membership.role if current_membership else Role.VIEWER)
            next_office = office if role_requires_office(next_role) else None
            if role_requires_office(next_role) and next_office is None and current_membership:
                next_office = current_membership.office
            if current_membership:
                current_membership.role = next_role
                current_membership.office = next_office
                current_membership.save(update_fields=["role", "office", "updated_at"])
            else:
                UserMembership.objects.create(
                    user=instance,
                    company=company,
                    office=next_office,
                    role=next_role,
                )
        return instance


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
    role = serializers.CharField()
    name = serializers.CharField()
    revision = serializers.IntegerField()
    default_permissions = serializers.ListField()


class RoleDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleDefinition
        fields = ("id", "code", "name", "description", "requires_office", "is_active", "sort_order")


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

    def validate_scope(self, value):
        if value not in PermissionScope.values:
            raise serializers.ValidationError("Invalid scope.")
        return value

    def validate_role(self, value):
        if not role_definition(value):
            raise serializers.ValidationError("Invalid role.")
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
    definition = role_definition(role)
    return {
        "role": role,
        "name": definition.name if definition else role,
        "requires_office": definition.requires_office if definition else True,
        "revision": role_template_revision(role),
        "default_permissions": [
            {"code": code, "scope": scope}
            for code, scope in sorted(grants.items())
        ],
    }
