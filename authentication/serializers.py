import re

import django.contrib.auth.password_validation as validators
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import serializers

from authentication.models import (
    SignupRequest,
    UsernameEmailLookup,
    normalize_lookup_email,
    normalize_lookup_username,
)
from core.models import (
    Company,
    CompanyOffice,
    CompanyRolePermissionOverride,
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
    is_metro_user,
    role_definition,
    role_requires_office,
    role_template_revision,
    template_role_grants,
)
from core.request_context import get_current_company

User = get_user_model()

WORKOS_PASSWORD_REQUIREMENT_MESSAGE = (
    "Password must be at least 10 characters and include 1 uppercase letter, "
    "1 lowercase letter, 1 number, and 1 special character."
)


class PasswordLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False, allow_blank=False)
    username = serializers.CharField(required=False, allow_blank=False)
    email = serializers.EmailField(required=False)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        identifier = data.get("identifier") or data.get("username") or data.get("email")
        if not identifier:
            raise serializers.ValidationError(
                {"identifier": "Email or username is required."}
            )
        data["identifier"] = identifier
        return data


class OtpStartSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False, allow_blank=False)
    email = serializers.EmailField(required=False)

    def validate(self, data):
        identifier = data.get("identifier") or data.get("email")
        if not identifier:
            raise serializers.ValidationError(
                {"identifier": "Email or username is required."}
            )
        data["identifier"] = identifier
        return data


class OtpVerifySerializer(OtpStartSerializer):
    code = serializers.CharField(min_length=4, max_length=12, trim_whitespace=True)


class EmailVerificationSerializer(serializers.Serializer):
    pending_authentication_token = serializers.CharField()
    code = serializers.CharField(min_length=4, max_length=12, trim_whitespace=True)


class SignupEmailVerificationSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=12, trim_whitespace=True)


class MfaChallengeSerializer(serializers.Serializer):
    authentication_factor_id = serializers.CharField()


class MfaVerifySerializer(serializers.Serializer):
    pending_authentication_token = serializers.CharField()
    authentication_challenge_id = serializers.CharField()
    code = serializers.CharField(min_length=4, max_length=12, trim_whitespace=True)


class OrganizationSelectionSerializer(serializers.Serializer):
    pending_authentication_token = serializers.CharField()
    organization_id = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)


class SignupRequestCreateSerializer(serializers.ModelSerializer):
    organization_id = serializers.CharField(write_only=True, trim_whitespace=True)
    phone = serializers.CharField(
        required=True, allow_blank=False, trim_whitespace=True
    )
    password = serializers.CharField(
        write_only=True, min_length=10, trim_whitespace=False
    )

    class Meta:
        model = SignupRequest
        fields = (
            "id",
            "full_name",
            "username",
            "email",
            "phone",
            "organization_id",
            "password",
            "status",
        )
        read_only_fields = ("id", "status")

    def validate_username(self, value):
        username = normalize_lookup_username(value)
        if not username:
            raise serializers.ValidationError("Username is required.")
        if "@" in username:
            raise serializers.ValidationError("Username must not be an email address.")
        if User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError("This username is already taken.")
        if UsernameEmailLookup.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError("This username is already taken.")
        if (
            SignupRequest.objects.filter(username__iexact=username)
            .exclude(status=SignupRequest.Status.REJECTED)
            .exists()
        ):
            raise serializers.ValidationError("This username is already taken.")
        return username

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email, is_active=True).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )
        if SignupRequest.objects.filter(
            email__iexact=email, status=SignupRequest.Status.PENDING
        ).exists():
            raise serializers.ValidationError(
                "A signup for this email is already pending approval."
            )
        if SignupRequest.objects.filter(
            email__iexact=email, status=SignupRequest.Status.APPROVED
        ).exists():
            raise serializers.ValidationError(
                "An account with this email has already been approved."
            )
        return email

    def validate_password(self, value):
        if (
            len(value) < 10
            or not re.search(r"[A-Z]", value)
            or not re.search(r"[a-z]", value)
            or not re.search(r"\d", value)
            or not re.search(r"[^A-Za-z0-9\s]", value)
        ):
            raise serializers.ValidationError(WORKOS_PASSWORD_REQUIREMENT_MESSAGE)
        return value

    def validate_phone(self, value):
        phone = value.strip()
        if not re.fullmatch(r"\d{10}", phone):
            raise serializers.ValidationError("Phone number must be exactly 10 digits.")
        return phone

    def validate_organization_id(self, value):
        organization_id = value.strip().upper()
        company = Company.objects.filter(
            signup_code=organization_id, is_active=True
        ).first()
        if not company:
            raise serializers.ValidationError("Enter a valid organization ID.")
        return organization_id

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Full name is required.")
        return value

    def create(self, validated_data):
        organization_id = validated_data.pop("organization_id")
        company = Company.objects.get(signup_code=organization_id, is_active=True)
        return SignupRequest.objects.create(
            **validated_data,
            company=company,
            company_name=company.name,
        )


class SignupRequestSerializer(serializers.ModelSerializer):
    company = serializers.PrimaryKeyRelatedField(read_only=True)
    company_id = serializers.ReadOnlyField()
    organization_id = serializers.ReadOnlyField(source="company.signup_code")
    user_id = serializers.ReadOnlyField()

    class Meta:
        model = SignupRequest
        fields = (
            "id",
            "full_name",
            "username",
            "email",
            "phone",
            "company_name",
            "organization_id",
            "company",
            "company_id",
            "user_id",
            "status",
            "workos_user_id",
            "workos_organization_id",
            "workos_organization_membership_id",
            "approved_at",
            "rejected_at",
            "rejection_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class SignupApprovalSerializer(serializers.Serializer):
    role = serializers.CharField()
    branch = serializers.PrimaryKeyRelatedField(
        source="office",
        queryset=CompanyOffice.objects.all(),
        required=False,
        allow_null=True,
    )

    def validate(self, data):
        signup_request = self.context["signup_request"]
        company = signup_request.company
        role = data.get("role")
        office = data.get("office")
        if not role_definition(role):
            raise serializers.ValidationError({"role": "Invalid role."})
        if role_requires_office(role) and not office:
            raise serializers.ValidationError(
                {"branch": "Branch is required for this role."}
            )
        if not role_requires_office(role) and office:
            raise serializers.ValidationError(
                {"branch": "Company-level roles must not include a branch."}
            )
        if office and company and not is_assignable_user_office(office, company):
            raise serializers.ValidationError(
                {"branch": "Branch cannot be assigned to users for this company."}
            )
        return data


class SignupRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


def assignable_user_offices(company):
    return (
        CompanyOffice.unscoped_objects.filter(
            company=company,
            is_active=True,
            status=OfficeStatus.ACTIVE,
        )
        .filter(
            Q(global_office__isnull=True)
            | Q(global_office__owner_company__isnull=True)
            | Q(global_office__owner_company=company)
        )
        .order_by("global_office__owner_company__name", "name")
    )


def is_assignable_user_office(office, company):
    if not office:
        return True
    return assignable_user_offices(company).filter(pk=office.pk).exists()


def display_user_office(office, company):
    if company and office and not is_assignable_user_office(office, company):
        return None
    return office


def validate_and_set_password(user, password):
    try:
        validators.validate_password(password, user)
    except ValidationError as exc:
        raise serializers.ValidationError({"password": list(exc.messages)})
    user.set_password(password)


def can_manage_metro_role(request_user, company):
    return bool(
        request_user
        and (
            request_user.is_superuser
            or request_user.is_owner
            or is_metro_user(request_user, company=company)
        )
    )


def includes_metro_membership(memberships):
    return any(membership.get("role") == Role.METRO for membership in memberships)


class UserMembershipSerializer(serializers.ModelSerializer):
    company_name = serializers.ReadOnlyField(source="company.name")
    company_signup_code = serializers.ReadOnlyField(source="company.signup_code")
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
            "company_signup_code",
            "office",
            "office_name",
            "branch",
            "branch_name",
            "role",
            "workos_organization_membership_id",
            "workos_role_slug",
            "permissions",
            "scoped_permissions",
        )
        read_only_fields = (
            "company",
            "workos_organization_membership_id",
            "workos_role_slug",
        )
        extra_kwargs = {"user": {"required": False}}

    def get_permissions(self, obj):
        return sorted(effective_membership_grants(obj).keys())

    def get_scoped_permissions(self, obj):
        return [
            {"code": code, "scope": scope}
            for code, scope in sorted(effective_membership_grants(obj).items())
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        office = display_user_office(instance.office, get_current_company())
        if office is None:
            data["office"] = None
            data["office_name"] = None
            data["branch"] = None
            data["branch_name"] = None
        return data

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError(
                {"company": "Active company context required."}
            )
        request_user = (
            self.context.get("request").user if self.context.get("request") else None
        )
        office = data.get("office", getattr(self.instance, "office", None))
        role = data.get("role", getattr(self.instance, "role", None))
        current_role = getattr(self.instance, "role", None)
        if (
            role == Role.METRO or current_role == Role.METRO
        ) and not can_manage_metro_role(request_user, company):
            raise serializers.ValidationError(
                {
                    "role": "Metro role assignments can only be changed by owners or Metro users."
                }
            )
        if role and not role_definition(role):
            raise serializers.ValidationError({"role": "Invalid role."})
        if role and role_requires_office(role) and not office:
            raise serializers.ValidationError(
                {"office": "Office is required for this role."}
            )
        if role and not role_requires_office(role) and office:
            raise serializers.ValidationError(
                {"office": "Company-level roles must not include an office."}
            )
        if office and not is_assignable_user_office(office, company):
            raise serializers.ValidationError(
                {"office": "Office cannot be assigned to users for the active company."}
            )
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
    membership_inputs = UserMembershipSerializer(
        many=True, write_only=True, required=False
    )
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
            "workos_user_id",
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
            "workos_user_id",
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

    def validate_username(self, value):
        username = normalize_lookup_username(value)
        if not username:
            raise serializers.ValidationError("Username is required.")
        if "@" in username:
            raise serializers.ValidationError("Username must not be an email address.")
        user_qs = User.objects.filter(username__iexact=username)
        lookup_qs = UsernameEmailLookup.objects.filter(username__iexact=username)
        signup_qs = SignupRequest.objects.filter(username__iexact=username).exclude(
            status=SignupRequest.Status.REJECTED
        )
        if self.instance:
            user_qs = user_qs.exclude(pk=self.instance.pk)
            existing_lookup = lookup_qs.first()
            if existing_lookup and existing_lookup.email != normalize_lookup_email(
                self.instance.email
            ):
                raise serializers.ValidationError("This username is already taken.")
            signup_qs = signup_qs.exclude(user=self.instance)
        elif lookup_qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        if user_qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        if signup_qs.exists():
            raise serializers.ValidationError("This username is already taken.")
        return username

    def to_representation(self, instance):
        data = super().to_representation(instance)
        company = get_current_company()
        office = display_user_office(instance.office, company)
        if office is None:
            data["branch"] = None
            data["branch_name"] = None
            data["office_name"] = None
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
            raise serializers.ValidationError(
                {"company": "Active company context required."}
            )
        request_user = (
            self.context.get("request").user if self.context.get("request") else None
        )
        memberships = data.get("membership_inputs") or []
        office = data.get("office", getattr(self.instance, "office", None))
        role = data.get("role")
        current_membership = None
        current_role = None
        if not role and self.instance:
            current_membership = self.instance.memberships.filter(
                company=company, is_active=True
            ).first()
            role = current_membership.role if current_membership else None
            office = office or (
                current_membership.office if current_membership else None
            )
        if self.instance and current_membership is None:
            current_membership = self.instance.memberships.filter(
                company=company, is_active=True
            ).first()
        current_role = current_membership.role if current_membership else None
        if (
            role == Role.METRO
            or current_role == Role.METRO
            or includes_metro_membership(memberships)
        ) and not can_manage_metro_role(request_user, company):
            raise serializers.ValidationError(
                {"role": "Metro users can only be changed by owners or Metro users."}
            )
        if not self.instance and not memberships and not role:
            raise serializers.ValidationError(
                {"membership_inputs": "At least one membership is required."}
            )
        if role == "":
            raise serializers.ValidationError({"role": "Role is required."})
        if role and not role_definition(role):
            raise serializers.ValidationError({"role": "Invalid role."})
        if role and role_requires_office(role) and not office:
            raise serializers.ValidationError(
                {"branch": "Default branch is required for this role."}
            )
        if role and not role_requires_office(role) and office:
            raise serializers.ValidationError(
                {"branch": "Company-level roles must not have a default branch."}
            )
        if office and not is_assignable_user_office(office, company):
            raise serializers.ValidationError(
                {
                    "branch": "This branch cannot be assigned to users for the active company."
                }
            )
        for membership in memberships:
            membership_office = membership.get("office")
            membership_role = membership.get("role")
            if membership_role and not role_definition(membership_role):
                raise serializers.ValidationError(
                    {"membership_inputs": "Invalid membership role."}
                )
            if (
                membership_role
                and role_requires_office(membership_role)
                and not membership_office
            ):
                raise serializers.ValidationError(
                    {
                        "membership_inputs": "Membership office is required for this role."
                    }
                )
            if (
                membership_role
                and not role_requires_office(membership_role)
                and membership_office
            ):
                raise serializers.ValidationError(
                    {
                        "membership_inputs": "Company-level roles must not include an office."
                    }
                )
            if membership_office and not is_assignable_user_office(
                membership_office, company
            ):
                raise serializers.ValidationError(
                    {
                        "membership_inputs": "Membership office cannot be assigned to users."
                    }
                )
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
        user.office = office or next(
            (
                membership.get("office")
                for membership in memberships
                if membership.get("office")
            ),
            None,
        )
        if password:
            # WorkOS owns usable credentials. Metro accepts the field for old
            # clients but never stores a Django password for app sign-in.
            user.set_unusable_password()
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
            instance.set_unusable_password()
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
            current_membership = instance.memberships.filter(
                company=company, is_active=True
            ).first()
            next_role = role or (
                current_membership.role if current_membership else Role.VIEWER
            )
            next_office = office if role_requires_office(next_role) else None
            if (
                role_requires_office(next_role)
                and next_office is None
                and current_membership
            ):
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
            raise serializers.ValidationError(
                {"new_password": "New password cannot be the same as the old password."}
            )
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
        fields = (
            "id",
            "code",
            "workos_role_slug",
            "name",
            "description",
            "requires_office",
            "is_active",
            "sort_order",
        )


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
        if value == Role.METRO:
            raise serializers.ValidationError(
                "Metro permissions are built in and cannot be changed."
            )
        return value

    def create(self, validated_data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError(
                {"company": "Active company context required."}
            )
        validated_data["company"] = company
        validated_data.setdefault(
            "based_on_template_revision", role_template_revision(validated_data["role"])
        )
        obj, _ = CompanyRolePermissionOverride.objects.update_or_create(
            company=company,
            role=validated_data["role"],
            permission=validated_data["permission"],
            defaults={
                "enabled": validated_data.get("enabled", True),
                "scope": validated_data.get("scope", PermissionScope.BRANCH),
                "based_on_template_revision": validated_data[
                    "based_on_template_revision"
                ],
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
            {"code": code, "scope": scope} for code, scope in sorted(grants.items())
        ],
    }
