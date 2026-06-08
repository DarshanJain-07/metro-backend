from rest_framework import permissions
from core.policies import has_role, can_manage_company
from core.models import Role
from core.request_context import get_current_company, get_current_branch

class AccountantPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN]):
            return True

        company = get_current_company()
        branch = get_current_branch()
        if not company:
            return False
        if branch:
            return has_role(request.user, company=company, branch=branch, roles=[Role.ACCOUNTANT])
        return False

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        if can_manage_company(request.user, obj.company):
            return True
            
        if hasattr(obj, 'branch'):
            return has_role(request.user, company=obj.company, branch=obj.branch, roles=[Role.ACCOUNTANT])

        return False
