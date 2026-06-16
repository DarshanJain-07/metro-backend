from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import (
    ChangePasswordView,
    CompanyRolePermissionOverrideViewSet,
    CompanyRolePermissionViewSet,
    LoginView,
    PermissionCatalogViewSet,
    RoleDefinitionViewSet,
    RoleTemplateViewSet,
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

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('', include(router.urls)),
]
