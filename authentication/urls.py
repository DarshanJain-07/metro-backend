from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import (
    AuthSyncView,
    ChangePasswordView,
    CompanyRolePermissionOverrideViewSet,
    CompanyRolePermissionViewSet,
    LoginView,
    LogoutView,
    MfaChallengeView,
    MfaVerifyView,
    MeView,
    OrganizationSelectionView,
    OtpStartView,
    OtpVerifyView,
    PasswordLoginView,
    PermissionCatalogViewSet,
    RoleDefinitionViewSet,
    RoleTemplateViewSet,
    SignupRequestViewSet,
    UserMembershipViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'memberships', UserMembershipViewSet, basename='membership')
router.register(r'permission-catalog', PermissionCatalogViewSet, basename='permission-catalog')
router.register(r'roles', RoleDefinitionViewSet, basename='role')
router.register(r'role-templates', RoleTemplateViewSet, basename='role-template')
router.register(r'company-role-permissions', CompanyRolePermissionViewSet, basename='company-role-permission')
router.register(r'company-role-overrides', CompanyRolePermissionOverrideViewSet, basename='company-role-override')
router.register(r'signup-requests', SignupRequestViewSet, basename='signup-request')

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('login/password/', PasswordLoginView.as_view(), name='login_password'),
    path('login/otp/start/', OtpStartView.as_view(), name='login_otp_start'),
    path('login/otp/verify/', OtpVerifyView.as_view(), name='login_otp_verify'),
    path('login/mfa/challenge/', MfaChallengeView.as_view(), name='login_mfa_challenge'),
    path('login/mfa/verify/', MfaVerifyView.as_view(), name='login_mfa_verify'),
    path('login/organization/select/', OrganizationSelectionView.as_view(), name='login_organization_select'),
    path('logout/', LogoutView.as_view(), name='auth_logout'),
    path('sync/', AuthSyncView.as_view(), name='auth_sync'),
    path('me/', MeView.as_view(), name='me'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('', include(router.urls)),
]
