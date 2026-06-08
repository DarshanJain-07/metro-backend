from rest_framework import permissions
from core.policies import (
    can_assign_delivery,
    can_book_docket,
    can_edit_docket,
    can_manage_company,
    can_mark_delivered,
    can_receive_incoming_load,
    has_role,
)
from core.models import Role
from core.request_context import get_current_company

class StrictActionPermission(permissions.BasePermission):
    """
    Granular action-level permission mapping using policies.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        action = getattr(view, 'action', None)
        
        if action in ['list', 'retrieve', 'incoming']:
            return True
            
        if action == 'create':
            # Create logic is enforced in the serializer, but we allow if they have ANY branch where they can create.
            # Coarse check: if they have any operational role or admin role.
            company = get_current_company()
            return has_role(request.user, company=company, roles=[
                Role.CLIENT_SUPER_ADMIN, Role.BRANCH_ADMIN, Role.BOOKING_USER
            ])

        if action in ['book', 'mark_in_transit', 'receive', 'assign_delivery', 'mark_delivered', 'cancel']:
             # These actions have more specific checks in has_object_permission or service
             return True

        return True

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        action = getattr(view, 'action', None)
        
        if action in ['list', 'retrieve']:
            return True
            
        if action in ['update', 'partial_update']:
            return can_edit_docket(request.user, obj)
            
        if action == 'destroy':
            return can_manage_company(request.user, obj.company)
            
        # Workflow Actions
        if action in ['book', 'cancel', 'mark_in_transit']:
            return can_book_docket(request.user, obj)
        
        if action == 'receive':
            return can_receive_incoming_load(request.user, obj)

        if action == 'assign_delivery':
            return can_assign_delivery(request.user, obj)

        if action == 'mark_delivered':
            return can_mark_delivered(request.user, obj)
            
        return False

class IsCompanyAdminPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        if getattr(view, 'action', None) in ['list', 'retrieve']:
            return True
            
        company = get_current_company()
        return can_manage_company(request.user, company)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        if getattr(view, 'action', None) in ['list', 'retrieve']:
            return True
            
        company = getattr(obj, 'company', None) or get_current_company()
        return can_manage_company(request.user, company)
