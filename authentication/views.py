from django.core.cache import caches
from django.shortcuts import redirect
from rest_framework import status, generics, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .serializers import (
    ChangePasswordSerializer,
    CompanyRolePermissionOverrideSerializer,
    GoogleExchangeSerializer,
    MfaChallengeSerializer,
    MfaVerifySerializer,
    OrganizationSelectionSerializer,
    OtpStartSerializer,
    OtpVerifySerializer,
    PasswordLoginSerializer,
    PermissionCatalogSerializer,
    RoleDefinitionSerializer,
    UserMembershipSerializer,
    UserSerializer,
    assignable_user_offices,
    role_template_payload,
)
from .permissions import UserManagementPermission
from .workos_service import (
    GENERIC_AUTH_ERROR,
    MetroAccessDenied,
    WorkOSAuthenticationFailed,
    WorkOSConfigurationError,
    WorkOSPendingAuthentication,
    as_plain_data,
    authenticate_with_code,
    authenticate_with_magic_auth,
    authenticate_with_organization_selection,
    authenticate_with_password,
    authenticate_with_totp,
    challenge_mfa_factor,
    consume_google_exchange_code,
    consume_google_state,
    create_google_exchange_code,
    create_google_pending_exchange_code,
    create_google_state,
    create_magic_auth,
    frontend_callback_url,
    get_workos_authorization_url,
    issue_metro_tokens,
    record_auth_event,
    request_ip,
    request_user_agent,
    resolve_identifier_email,
    sync_current_user_from_workos,
    sync_workos_authentication,
)
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


class OtpThrottle(AnonRateThrottle):
    scope = "otp_attempts"
    cache = caches["throttle"]


class OAuthThrottle(AnonRateThrottle):
    scope = "oauth_attempts"
    cache = caches["throttle"]


def _auth_response_identity(auth_response):
    data = as_plain_data(auth_response)
    workos_user = as_plain_data(data.get("user"))
    return (
        workos_user.get("id") or workos_user.get("user_id") or "",
        data.get("organization_id") or data.get("organizationId") or "",
    )


def _user_with_relations(user):
    return User.objects.select_related("company", "office").prefetch_related(
        "memberships",
        "memberships__company",
        "memberships__office",
    ).get(pk=user.pk)


def _pending_response(request, event_type, exc):
    record_auth_event(
        event_type,
        "PENDING",
        request,
        metadata={"pending_type": exc.payload.get("type")},
    )
    return Response(exc.payload, status=status.HTTP_202_ACCEPTED)


def _workos_config_response():
    return Response({"detail": "Authentication is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


def _complete_workos_auth(request, auth_response, event_type):
    workos_user_id, workos_organization_id = _auth_response_identity(auth_response)
    try:
        user, company = sync_workos_authentication(auth_response)
    except (MetroAccessDenied, WorkOSAuthenticationFailed):
        record_auth_event(
            event_type,
            "FAILURE",
            request,
            workos_user_id=workos_user_id,
            workos_organization_id=workos_organization_id,
            metadata={"reason": "metro_access_denied"},
        )
        return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_403_FORBIDDEN)

    user = _user_with_relations(user)
    user_logged_in.send(sender=user.__class__, request=request, user=user)
    record_auth_event(
        event_type,
        "SUCCESS",
        request,
        actor=user,
        target_user=user,
        company=company,
        workos_user_id=workos_user_id,
        workos_organization_id=workos_organization_id,
        metadata={"ip_address": request_ip(request), "user_agent": request_user_agent(request)},
    )
    tokens = issue_metro_tokens(user)
    return Response({
        **tokens,
        "user": UserSerializer(user).data,
    })


def _sync_google_callback_auth(request, auth_response):
    workos_user_id, workos_organization_id = _auth_response_identity(auth_response)
    try:
        user, company = sync_workos_authentication(auth_response)
    except (MetroAccessDenied, WorkOSAuthenticationFailed) as exc:
        record_auth_event(
            "auth.login.google.callback",
            "FAILURE",
            request,
            workos_user_id=workos_user_id,
            workos_organization_id=workos_organization_id,
            metadata={"reason": "metro_access_denied"},
        )
        raise WorkOSAuthenticationFailed() from exc
    user = _user_with_relations(user)
    record_auth_event(
        "auth.login.google.callback",
        "SUCCESS",
        request,
        actor=user,
        target_user=user,
        company=company,
        workos_user_id=workos_user_id,
        workos_organization_id=workos_organization_id,
        metadata={"method": "google"},
    )
    return user


class LoginView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = TokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        return Response(
            {"detail": "Django password login is deprecated. Use /api/v1/auth/login/password/."},
            status=status.HTTP_410_GONE,
        )


class PasswordLoginView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = PasswordLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = resolve_identifier_email(serializer.validated_data["identifier"])
        try:
            auth_response = authenticate_with_password(email, serializer.validated_data["password"], request)
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.password", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            record_auth_event("auth.login.password", "FAILURE", request, metadata={"method": "password"})
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        return _complete_workos_auth(request, auth_response, "auth.login.password")


class OtpStartView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [OtpThrottle]
    serializer_class = OtpStartSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = resolve_identifier_email(serializer.validated_data["identifier"])
        try:
            create_magic_auth(email)
            record_auth_event("auth.login.otp.start", "SUCCESS", request, metadata={"method": "otp"})
        except WorkOSConfigurationError:
            return _workos_config_response()
        except (WorkOSAuthenticationFailed, WorkOSPendingAuthentication):
            record_auth_event("auth.login.otp.start", "FAILURE", request, metadata={"method": "otp"})
        return Response({"detail": "If your account exists, a sign-in code has been sent."})


class OtpVerifyView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [OtpThrottle]
    serializer_class = OtpVerifySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = resolve_identifier_email(serializer.validated_data["identifier"])
        try:
            auth_response = authenticate_with_magic_auth(email, serializer.validated_data["code"], request)
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.otp.verify", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            record_auth_event("auth.login.otp.verify", "FAILURE", request, metadata={"method": "otp"})
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        return _complete_workos_auth(request, auth_response, "auth.login.otp.verify")


class MfaChallengeView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = MfaChallengeSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            challenge = challenge_mfa_factor(serializer.validated_data["authentication_factor_id"])
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.mfa.challenge", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        data = as_plain_data(challenge)
        return Response({
            "authentication_challenge_id": data.get("id") or data.get("authentication_challenge_id"),
        })


class MfaVerifyView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = MfaVerifySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            auth_response = authenticate_with_totp(
                serializer.validated_data["pending_authentication_token"],
                serializer.validated_data["authentication_challenge_id"],
                serializer.validated_data["code"],
                request,
            )
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.mfa.verify", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            record_auth_event("auth.login.mfa.verify", "FAILURE", request, metadata={"method": "mfa"})
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        return _complete_workos_auth(request, auth_response, "auth.login.mfa.verify")


class OrganizationSelectionView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = OrganizationSelectionSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            auth_response = authenticate_with_organization_selection(
                serializer.validated_data["pending_authentication_token"],
                serializer.validated_data["organization_id"],
                request,
            )
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.organization.select", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            record_auth_event("auth.login.organization.select", "FAILURE", request, metadata={"method": "organization_selection"})
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        return _complete_workos_auth(request, auth_response, "auth.login.organization.select")


class GoogleStartView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [OAuthThrottle]

    def get(self, request, *args, **kwargs):
        state = create_google_state(request.query_params.get("redirect_url"))
        try:
            authorization_url = get_workos_authorization_url(state)
        except WorkOSConfigurationError:
            return _workos_config_response()
        return Response({"authorization_url": authorization_url})


class GoogleCallbackView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [OAuthThrottle]

    def get(self, request, *args, **kwargs):
        redirect_url = "/dockets/new"
        try:
            redirect_url = consume_google_state(request.query_params.get("state", ""))
            code = request.query_params.get("code")
            if not code:
                raise WorkOSAuthenticationFailed()
            auth_response = authenticate_with_code(code, request)
            user = _sync_google_callback_auth(request, auth_response)
            exchange_code = create_google_exchange_code(user, redirect_url)
            return redirect(frontend_callback_url({"workos_exchange_code": exchange_code, "redirect_url": redirect_url}))
        except WorkOSPendingAuthentication as exc:
            record_auth_event(
                "auth.login.google.callback",
                "PENDING",
                request,
                metadata={"method": "google", "pending_type": exc.payload.get("type")},
            )
            exchange_code = create_google_pending_exchange_code(exc.payload, redirect_url)
            return redirect(frontend_callback_url({"workos_exchange_code": exchange_code, "redirect_url": redirect_url}))
        except (WorkOSAuthenticationFailed, WorkOSConfigurationError):
            record_auth_event("auth.login.google.callback", "FAILURE", request, metadata={"method": "google"})
            return redirect(frontend_callback_url({"auth_error": "google_failed", "redirect_url": redirect_url}))


class GoogleExchangeView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [OAuthThrottle]
    serializer_class = GoogleExchangeSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = consume_google_exchange_code(serializer.validated_data["exchange_code"])
        except WorkOSAuthenticationFailed:
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)

        if payload.get("pending"):
            return Response(payload["pending"], status=status.HTTP_202_ACCEPTED)

        try:
            user = _user_with_relations(User.objects.get(pk=payload["user_id"]))
        except User.DoesNotExist:
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        tokens = issue_metro_tokens(user)
        user_logged_in.send(sender=user.__class__, request=request, user=user)
        record_auth_event(
            "auth.login.google.exchange",
            "SUCCESS",
            request,
            actor=user,
            target_user=user,
            company=user.memberships.filter(is_active=True).first().company if user.memberships.filter(is_active=True).exists() else None,
            workos_user_id=user.workos_user_id or "",
            metadata={"method": "google"},
        )
        return Response({
            **tokens,
            "user": UserSerializer(user).data,
        })


class AuthSyncView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        company = get_current_company()
        try:
            user = sync_current_user_from_workos(request.user, company)
        except (MetroAccessDenied, WorkOSAuthenticationFailed):
            record_auth_event("auth.sync", "FAILURE", request, actor=request.user, target_user=request.user, company=company)
            return Response({"detail": "Your app access is no longer active."}, status=status.HTTP_403_FORBIDDEN)
        except WorkOSConfigurationError:
            return _workos_config_response()
        user = _user_with_relations(user)
        record_auth_event(
            "auth.sync",
            "SUCCESS",
            request,
            actor=user,
            target_user=user,
            company=company,
            workos_user_id=user.workos_user_id or "",
            workos_organization_id=company.workos_organization_id if company else "",
        )
        return Response(UserSerializer(user).data)


class MeView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = User.objects.select_related('company', 'office').prefetch_related(
            'memberships',
            'memberships__company',
            'memberships__office',
        ).get(pk=request.user.pk)
        return Response(UserSerializer(user).data)


class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        return Response({
            "detail": "Password changes are managed by WorkOS.",
        }, status=status.HTTP_410_GONE)

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
        offices = assignable_user_offices(company).select_related(
            "city",
            "city__state",
            "global_office",
            "global_office__owner_company",
        )
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
