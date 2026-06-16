from django.core.cache import caches
from rest_framework import status, generics, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    ChangePasswordSerializer,
    CompanyRolePermissionOverrideSerializer,
    PermissionCatalogSerializer,
    RoleDefinitionSerializer,
    UserMembershipSerializer,
    UserSerializer,
    assignable_user_offices,
    role_template_payload,
)
from .permissions import UserManagementPermission
from core.models import CompanyRolePermissionOverride, PermissionCatalog, RoleDefinition, UserMembership
from core.serializers import CompanyOfficeSerializer
from core.policies import (
    active_role_definitions,
    can,
    can_manage_company,
    default_role_definition_payloads,
    effective_role_grants,
    seed_role_templates,
)
from core.request_context import get_current_company

User = get_user_model()

class LoginThrottle(AnonRateThrottle):
    scope = 'login_attempts'
    cache = caches['throttle']

class LoginView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = TokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.user
        
        # FIX: Resolve N+1 query issue for the UserSerializer relations
        user_with_relations = User.objects.select_related('company', 'office').prefetch_related('memberships', 'memberships__company', 'memberships__office').get(pk=user.pk)

        # Log the login action (triggers Django signals, useful for Audit Trails)
        user_logged_in.send(sender=user_with_relations.__class__, request=request, user=user_with_relations)
        
        return Response({
            'access': serializer.validated_data['access'],
            'refresh': serializer.validated_data['refresh'],
            'user': UserSerializer(user_with_relations).data
        })

class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            
            # Keep the user's browser session alive (e.g., for Django Admin)
            update_session_auth_hash(request, user)

            outstanding_tokens = OutstandingToken.objects.filter(user=user)
            for token in outstanding_tokens:
                BlacklistedToken.objects.get_or_create(token=token)

            refresh = RefreshToken.for_user(user)
        
        return Response({
            "detail": "Password has been updated successfully.",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }, status=status.HTTP_200_OK)

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.order_by("id")
    serializer_class = UserSerializer
    permission_classes = [UserManagementPermission]

    def get_queryset(self):
        base_qs = User.objects.select_related("company", "office").prefetch_related(
            "memberships",
            "memberships__company",
            "memberships__office",
        ).order_by("id")
        user = self.request.user
        if can_manage_company(user, None):
            return base_qs
        
        company = get_current_company()
        if company:
            return base_qs.filter(memberships__company=company, memberships__is_active=True).distinct()
        return base_qs.none()

    def perform_create(self, serializer):
        company = get_current_company()
        serializer.save(company=company)

    @action(detail=False, methods=["get"], url_path="assignable-branches")
    def assignable_branches(self, request):
        company = get_current_company()
        if not company:
            return Response({"detail": "Active company context required."}, status=status.HTTP_400_BAD_REQUEST)
        offices = assignable_user_offices(company).select_related("city", "city__state", "global_office")
        return Response(CompanyOfficeSerializer(offices, many=True).data)

class UserMembershipViewSet(viewsets.ModelViewSet):
    queryset = UserMembership.objects.all()
    serializer_class = UserMembershipSerializer
    permission_classes = [UserManagementPermission]

    def get_queryset(self):
        user = self.request.user
        if can_manage_company(user, None):
            return UserMembership.objects.all()
        
        company = get_current_company()
        if company:
            return UserMembership.objects.filter(company=company)
        return UserMembership.objects.none()

    def perform_create(self, serializer):
        company = get_current_company()
        if not serializer.validated_data.get('user'):
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({"user": "User is required."})
        serializer.save(company=company)


class RolePermissionAdminPermission(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser:
            return True
        company = get_current_company()
        return bool(company and can(request.user, "roles:manage", company=company))


class PermissionCatalogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PermissionCatalogSerializer
    permission_classes = [RolePermissionAdminPermission]
    queryset = PermissionCatalog.objects.filter(is_active=True).order_by("group", "code")

    def get_queryset(self):
        seed_role_templates()
        return super().get_queryset()


class RoleDefinitionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RoleDefinitionSerializer
    permission_classes = [RolePermissionAdminPermission]

    def get_queryset(self):
        return active_role_definitions()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if isinstance(queryset, list):
            return Response(default_role_definition_payloads())
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class RoleTemplateViewSet(viewsets.ViewSet):
    permission_classes = [RolePermissionAdminPermission]

    def list(self, request):
        seed_role_templates()
        return Response([role_template_payload(role.code) for role in active_role_definitions()])


class CompanyRolePermissionViewSet(viewsets.ViewSet):
    permission_classes = [RolePermissionAdminPermission]

    def list(self, request):
        seed_role_templates()
        company = get_current_company()
        role = request.query_params.get("role")
        roles = [role] if role else [item.code for item in active_role_definitions()]
        payload = []
        for role_name in roles:
            grants = effective_role_grants(company, role_name)
            payload.append(
                {
                    "role": role_name,
                    "permissions": [
                        {"code": code, "scope": scope}
                        for code, scope in sorted(grants.items())
                    ],
                }
            )
        return Response(payload)


class CompanyRolePermissionOverrideViewSet(viewsets.ModelViewSet):
    serializer_class = CompanyRolePermissionOverrideSerializer
    permission_classes = [RolePermissionAdminPermission]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        seed_role_templates()
        company = get_current_company()
        if not company:
            return CompanyRolePermissionOverride.objects.none()
        qs = CompanyRolePermissionOverride.objects.filter(company=company).select_related("permission")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        return qs
