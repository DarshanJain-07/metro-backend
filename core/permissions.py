from rest_framework import permissions

from core.policies import can
from core.request_context import get_current_company, get_current_office


class BusinessActionPermission(permissions.BasePermission):
    default_action_map = {
        "list": "view",
        "retrieve": "view",
        "create": "create",
        "update": "edit",
        "partial_update": "edit",
        "destroy": "delete",
    }

    def _required_permission(self, view):
        explicit = getattr(view, "action_permissions", {})
        action = getattr(view, "action", None)
        if action in explicit:
            return explicit[action]
        resource = getattr(view, "permission_resource", None)
        permission_action = self.default_action_map.get(action)
        if resource and permission_action:
            return f"{resource}:{permission_action}"
        return None

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        permission = self._required_permission(view)
        if not permission:
            return False
        return can(
            request.user,
            permission,
            company=get_current_company(),
            office=get_current_office(),
        )

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        permission = self._required_permission(view)
        if not permission:
            return False
        return can(
            request.user,
            permission,
            company=getattr(obj, "company", get_current_company()),
            office=getattr(obj, "office", get_current_office()),
            resource=obj,
        )
