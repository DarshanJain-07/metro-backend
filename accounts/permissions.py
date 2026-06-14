from rest_framework import permissions

from core.policies import can, can_manage_company
from core.request_context import get_current_company, get_current_office


class AccountingActionPermission(permissions.BasePermission):
    resource = None
    action_permissions = {}

    def _permission(self, request, view):
        action = getattr(view, "action", None)
        if action in self.action_permissions:
            return self.action_permissions[action]
        resource = getattr(view, "permission_resource", self.resource)
        if not resource:
            return None
        if action in ("list", "retrieve"):
            return f"{resource}:view"
        if action == "create":
            return f"{resource}:create"
        if action in ("update", "partial_update"):
            return f"{resource}:edit"
        if action == "destroy":
            return f"{resource}:delete"
        return f"{resource}:view" if request.method in permissions.SAFE_METHODS else f"{resource}:create"

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        company = get_current_company()
        if not company:
            return False
        action = self._permission(request, view)
        if not action:
            return False
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
            action = self._permission(request, view)
            return can(request.user, action, company=obj.company, office=obj.office)
        return False


class AccountantPermission(AccountingActionPermission):
    resource = "invoice"
