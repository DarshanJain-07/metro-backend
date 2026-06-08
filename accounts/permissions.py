from rest_framework import permissions

from core.policies import can, can_manage_company
from core.request_context import get_current_company, get_current_office


class AccountantPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        company = get_current_company()
        if not company:
            return False
        action = "billing:view" if request.method in permissions.SAFE_METHODS else "billing:create"
        office = get_current_office()
        if office:
            return can(request.user, action, company=company, office=office)
        return can_manage_company(request.user, company) or can(request.user, action, company=company)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if can_manage_company(request.user, obj.company):
            return True
        if hasattr(obj, "office"):
            action = "billing:view" if request.method in permissions.SAFE_METHODS else "billing:create"
            return can(request.user, action, company=obj.company, office=obj.office)
        return False
