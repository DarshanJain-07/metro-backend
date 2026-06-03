from rest_framework import permissions
from core.policies import has_role, can_manage_company
from core.models import Role

class UserManagementPermission(permissions.BasePermission):
    """
    Permission class to ensure only admins can manage users and memberships.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        # Platform admins and superusers can do anything
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        # Allow safe methods for all authenticated users (get_queryset handles scoping)
        if request.method in permissions.SAFE_METHODS:
            return True

        # For mutations, we check if they are a Client Super Admin for their company
        from core.request_context import get_current_company
        company = get_current_company()
        if not company:
            return False
            
        # Only CLIENT_SUPER_ADMIN can manage (create/update/delete) users/memberships
        return has_role(request.user, company=company, roles=[Role.CLIENT_SUPER_ADMIN])

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        # Allow safe methods (get_queryset should have already filtered these, but good to have)
        if request.method in permissions.SAFE_METHODS:
            return True

        # Check if they can manage the company of the object
        if hasattr(obj, 'company'):
            return can_manage_company(request.user, obj.company)
            
        return False
