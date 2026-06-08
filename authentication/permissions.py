from rest_framework import permissions
from core.policies import can, can_manage_company

class UserManagementPermission(permissions.BasePermission):
    """
    Permission class to ensure only admins can manage users and memberships.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        # Platform admins and superusers can do anything
        if request.user.is_superuser:
            return True

        # Allow safe methods for all authenticated users (get_queryset handles scoping)
        if request.method in permissions.SAFE_METHODS:
            return True

        # For mutations, we check if they are a Client Super Admin for their company
        from core.request_context import get_current_company, get_current_office
        company = get_current_company()
        if not company:
            return False

        office = get_current_office()
        if office:
            return can(request.user, "users:manage", company=company, office=office)
        return can(request.user, "users:manage", company=company)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser:
            return True

        # Allow safe methods (get_queryset should have already filtered these, but good to have)
        if request.method in permissions.SAFE_METHODS:
            return True

        if hasattr(obj, 'company'):
            if can_manage_company(request.user, obj.company):
                return True
            office = getattr(obj, "office", None)
            if office is None:
                return False
            return can(request.user, "users:manage", company=obj.company, office=office)

        return False
