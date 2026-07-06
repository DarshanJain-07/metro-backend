from django.core.cache import caches
from rest_framework import status, generics, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import (
    ChangePasswordSerializer,
    CompanyRolePermissionOverrideSerializer,
    EmailVerificationSerializer,
    LogoutSerializer,
    MfaChallengeSerializer,
    MfaVerifySerializer,
    OrganizationSelectionSerializer,
    OtpStartSerializer,
    OtpVerifySerializer,
    PasswordLoginSerializer,
    PermissionCatalogSerializer,
    RoleDefinitionSerializer,
    SignupApprovalSerializer,
    SignupEmailVerificationSerializer,
    SignupRejectSerializer,
    SignupRequestCreateSerializer,
    SignupRequestSerializer,
    UserMembershipSerializer,
    UserSerializer,
    assignable_user_offices,
    role_template_payload,
)
from .permissions import SignupRequestPermission, UserManagementPermission
from .workos_service import (
    GENERIC_AUTH_ERROR,
    MetroAccessDenied,
    WorkOSAuthenticationFailed,
    WorkOSConfigurationError,
    WorkOSPendingAuthentication,
    UsernameLookupNotFound,
    as_plain_data,
    authenticate_with_magic_auth,
    authenticate_with_organization_selection,
    authenticate_with_password,
    authenticate_with_totp,
    challenge_mfa_factor,
    create_magic_auth,
    issue_metro_tokens,
    record_auth_event,
    request_ip,
    request_user_agent,
    resolve_identifier_email,
    scrub_metadata,
    sync_current_user_from_workos,
    sync_workos_authentication,
    approve_pending_signup,
    create_pending_signup,
    notify_owner_of_signup,
    pending_access_approval_payload,
    signup_email_verification_payload,
    verify_pending_signup_email,
)
from authentication.models import SignupRequest
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


class SignupThrottle(AnonRateThrottle):
    scope = "signup_attempts"
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


def _auth_failure_metadata(method, exc=None):
    metadata = {"method": method}
    if exc is not None:
        metadata["exception"] = exc.__class__.__name__
        message = str(exc)
        if message:
            metadata["message"] = message
    payload = getattr(exc, "payload", None)
    if payload:
        metadata["workos_error"] = scrub_metadata(payload)
    return metadata


def _complete_workos_auth(request, auth_response, event_type):
    workos_user_id, workos_organization_id = _auth_response_identity(auth_response)
    try:
        user, company = sync_workos_authentication(auth_response)
    except WorkOSPendingAuthentication as exc:
        return _pending_response(request, event_type, exc)
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
        try:
            email = resolve_identifier_email(serializer.validated_data["identifier"])
            auth_response = authenticate_with_password(email, serializer.validated_data["password"], request)
        except UsernameLookupNotFound:
            record_auth_event("auth.login.password", "FAILURE", request, metadata={"method": "password", "reason": "username_not_found"})
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
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
        try:
            email = resolve_identifier_email(serializer.validated_data["identifier"])
            create_magic_auth(email)
            record_auth_event("auth.login.otp.start", "SUCCESS", request, metadata={"method": "otp"})
        except UsernameLookupNotFound:
            record_auth_event("auth.login.otp.start", "FAILURE", request, metadata={"method": "otp", "reason": "username_not_found"})
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
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
        try:
            email = resolve_identifier_email(serializer.validated_data["identifier"])
            auth_response = authenticate_with_magic_auth(email, serializer.validated_data["code"], request)
        except UsernameLookupNotFound:
            record_auth_event("auth.login.otp.verify", "FAILURE", request, metadata={"method": "otp", "reason": "username_not_found"})
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.otp.verify", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            record_auth_event("auth.login.otp.verify", "FAILURE", request, metadata={"method": "otp"})
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        return _complete_workos_auth(request, auth_response, "auth.login.otp.verify")


class EmailVerificationView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = EmailVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            auth_response = authenticate_with_email_verification(
                serializer.validated_data["pending_authentication_token"],
                serializer.validated_data["code"],
                request,
            )
        except WorkOSPendingAuthentication as exc:
            return _pending_response(request, "auth.login.email.verify", exc)
        except WorkOSConfigurationError:
            return _workos_config_response()
        except WorkOSAuthenticationFailed:
            record_auth_event("auth.login.email.verify", "FAILURE", request, metadata={"method": "email_verification"})
            return Response({"detail": GENERIC_AUTH_ERROR}, status=status.HTTP_401_UNAUTHORIZED)
        return _complete_workos_auth(request, auth_response, "auth.login.email.verify")


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


class SignupRequestViewSet(viewsets.ModelViewSet):
    queryset = SignupRequest.objects.select_related("company", "user").order_by("-created_at")
    serializer_class = SignupRequestSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        if self.action in {"create", "verify_email"}:
            return [AllowAny()]
        return [SignupRequestPermission()]

    def get_throttles(self):
        if self.action in {"create", "verify_email"}:
            return [SignupThrottle()]
        return super().get_throttles()

    def get_serializer_class(self):
        if self.action == "create":
            return SignupRequestCreateSerializer
        return SignupRequestSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
        if self.request.user.is_superuser or self.request.user.is_owner:
            return queryset
        company = get_current_company()
        if company:
            return queryset.filter(company=company)
        return queryset.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = serializer.validated_data.pop("password")
        signup_request = serializer.save()
        try:
            signup_request = create_pending_signup(signup_request, password)
            record_auth_event(
                "auth.signup.create",
                "PENDING",
                request,
                target_user=signup_request.user,
                company=signup_request.company,
                workos_user_id=signup_request.workos_user_id,
                workos_organization_id=signup_request.workos_organization_id,
                metadata={"signup_request_id": signup_request.id},
            )
        except WorkOSConfigurationError:
            signup_request.delete()
            return _workos_config_response()
        except Exception as exc:
            signup_request.delete()
            record_auth_event(
                "auth.signup.create",
                "FAILURE",
                request,
                metadata=_auth_failure_metadata("signup", exc),
            )
            return Response({"detail": "Could not complete signup. Please try again."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(signup_email_verification_payload(signup_request), status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"], url_path="verify-email")
    def verify_email(self, request, pk=None):
        signup_request = SignupRequest.objects.select_related("company", "user").filter(pk=pk).first()
        if not signup_request:
            return Response({"detail": "Signup request not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SignupEmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        should_notify_owner = signup_request.status == SignupRequest.Status.EMAIL_VERIFICATION_PENDING
        try:
            signup_request = verify_pending_signup_email(
                signup_request,
                serializer.validated_data["code"],
            )
            if should_notify_owner:
                notify_owner_of_signup(signup_request, request=request)
            record_auth_event(
                "auth.signup.email.verify",
                "SUCCESS",
                request,
                target_user=signup_request.user,
                company=signup_request.company,
                workos_user_id=signup_request.workos_user_id,
                workos_organization_id=signup_request.workos_organization_id,
                metadata={"signup_request_id": signup_request.id},
            )
        except WorkOSConfigurationError:
            return _workos_config_response()
        except (MetroAccessDenied, WorkOSAuthenticationFailed) as exc:
            record_auth_event(
                "auth.signup.email.verify",
                "FAILURE",
                request,
                target_user=signup_request.user,
                company=signup_request.company,
                workos_user_id=signup_request.workos_user_id,
                workos_organization_id=signup_request.workos_organization_id,
                metadata=_auth_failure_metadata("signup_email_verify", exc),
            )
            return Response({"detail": "Could not verify email code."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            pending_access_approval_payload(
                user=signup_request.user,
                email=signup_request.email,
                company=signup_request.company,
            ),
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        signup_request = self.get_object()
        serializer = SignupApprovalSerializer(
            data=request.data,
            context={"request": request, "signup_request": signup_request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            signup_request = approve_pending_signup(
                signup_request,
                request.user,
                role=serializer.validated_data["role"],
                office=serializer.validated_data.get("office"),
            )
        except WorkOSConfigurationError:
            return _workos_config_response()
        except MetroAccessDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            record_auth_event(
                "auth.signup.approve",
                "FAILURE",
                request,
                target_user=signup_request.user,
                company=signup_request.company,
                workos_user_id=signup_request.workos_user_id,
                workos_organization_id=signup_request.workos_organization_id,
                metadata=_auth_failure_metadata("signup_approve", exc),
            )
            return Response({"detail": "Could not approve signup."}, status=status.HTTP_400_BAD_REQUEST)
        record_auth_event(
            "auth.signup.approve",
            "SUCCESS",
            request,
            actor=request.user,
            target_user=signup_request.user,
            company=signup_request.company,
            workos_user_id=signup_request.workos_user_id,
            workos_organization_id=signup_request.workos_organization_id,
            metadata={"signup_request_id": signup_request.id},
        )
        return Response(SignupRequestSerializer(signup_request).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        signup_request = self.get_object()
        serializer = SignupRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if signup_request.status != SignupRequest.Status.PENDING:
            return Response({"detail": "Signup request is not pending."}, status=status.HTTP_400_BAD_REQUEST)
        signup_request.mark_rejected(request.user, serializer.validated_data.get("reason", ""))
        signup_request.save()
        record_auth_event(
            "auth.signup.reject",
            "SUCCESS",
            request,
            actor=request.user,
            target_user=signup_request.user,
            company=signup_request.company,
            workos_user_id=signup_request.workos_user_id,
            workos_organization_id=signup_request.workos_organization_id,
            metadata={"signup_request_id": signup_request.id},
        )
        return Response(SignupRequestSerializer(signup_request).data)


class MeView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = User.objects.select_related('company', 'office').prefetch_related(
            'memberships',
            'memberships__company',
            'memberships__office',
        ).get(pk=request.user.pk)
        return Response(UserSerializer(user).data)


class LogoutView(generics.GenericAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        revoked = True
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            revoked = False

        return Response({"ok": True, "revoked": revoked})


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
