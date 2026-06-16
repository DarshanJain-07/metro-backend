from rest_framework import permissions
from core.policies import can, can_manage_company, effective_membership_grants, role_requires_office


def _request_resets_password(request):
    password = request.data.get("password") if hasattr(request, "data") else None
    return password not in (None, "")


def _action_resets_password(request, view):
    return getattr(view, "action", None) in {"update", "partial_update"} and _request_resets_password(request)


def _target_memberships(user, company):
    return list(
        user.memberships.filter(company=company, is_active=True).select_related("office")
    )


def can_reset_target_password(actor, target, company, office=None):
    if not company:
        return False

    if actor.is_superuser or can_manage_company(actor, company):
        return True

    if not office or actor == target:
        return False

    memberships = _target_memberships(target, company)
    if not memberships:
        return False

    for membership in memberships:
        if not role_requires_office(membership.role):
            return False
        if "users:reset_password" in effective_membership_grants(membership):
            return False
        if membership.office_id != office.id:
            return False

    return can(actor, "users:reset_password", company=company, office=office)


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

        from core.request_context import get_current_company, get_current_office
        company = get_current_company()
        office = get_current_office()

        if request.method in permissions.SAFE_METHODS:
            return bool(company and can(request.user, "users:view", company=company, office=office))

        if not company:
            return False

        action = getattr(view, "action", None)
        if _action_resets_password(request, view):
            permission = "users:reset_password"
        else:
            permission = {
                "create": "users:create",
                "update": "users:edit",
                "partial_update": "users:edit",
                "destroy": "users:delete",
            }.get(action, "users:edit")
        if office:
            return can(request.user, permission, company=company, office=office)
        return can(request.user, permission, company=company)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser:
            return True

        # Allow safe methods (get_queryset should have already filtered these, but good to have)
        if request.method in permissions.SAFE_METHODS:
            return True

        from core.request_context import get_current_company, get_current_office

        if hasattr(obj, 'company'):
            company = get_current_company() or obj.company
            if _action_resets_password(request, view):
                return can_reset_target_password(request.user, obj, company, get_current_office())

            if can_manage_company(request.user, obj.company):
                return True
            office = getattr(obj, "office", None)
            if office is None:
                return False
            return can(request.user, "users:edit", company=obj.company, office=office)

        return False
