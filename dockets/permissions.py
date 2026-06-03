from rest_framework import permissions
from core.policies import has_role, can_manage_company, can_create_docket, can_edit_docket
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
            # Typically origin branch tasks
            return has_role(request.user, company=obj.company, branch=obj.origin_branch, roles=[Role.BRANCH_ADMIN, Role.BOOKING_USER]) or \
                   has_role(request.user, company=obj.company, roles=[Role.CLIENT_SUPER_ADMIN])
        
        if action == 'receive':
            # Destination branch task
            return has_role(request.user, company=obj.company, branch=obj.destination_branch, roles=[Role.BRANCH_ADMIN, Role.BOOKING_USER]) or \
                   has_role(request.user, company=obj.company, roles=[Role.CLIENT_SUPER_ADMIN])

        if action in ['assign_delivery', 'mark_delivered']:
            # Destination branch task, delivery user can mark delivered
            if action == 'mark_delivered' and has_role(request.user, company=obj.company, roles=[Role.DELIVERY_USER]):
                 # Delivery user can only mark delivered if they are assigned? 
                 # For now, let's allow if they have the role and belong to the branch
                 return has_role(request.user, company=obj.company, branch=obj.destination_branch, roles=[Role.DELIVERY_USER, Role.BRANCH_ADMIN])
            
            return has_role(request.user, company=obj.company, branch=obj.destination_branch, roles=[Role.BRANCH_ADMIN]) or \
                   has_role(request.user, company=obj.company, roles=[Role.CLIENT_SUPER_ADMIN])
            
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
