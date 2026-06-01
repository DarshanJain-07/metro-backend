from rest_framework import permissions

class StrictActionPermission(permissions.BasePermission):
    """
    Granular action-level permission mapping.
    - list/retrieve: view
    - create: add
    - update/partial_update: change
    - destroy: delete
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        # Superusers can do anything
        if request.user.is_superuser:
            return True

        queryset = getattr(view, 'queryset', None)
        if queryset is None:
            return False
            
        app_label = queryset.model._meta.app_label
        model_name = queryset.model._meta.model_name
        
        action = view.action
        
        if action in ['list', 'retrieve']:
            perm_name = f'view_{model_name}'
        elif action == 'create':
            perm_name = f'add_{model_name}'
        elif action in ['update', 'partial_update']:
            perm_name = f'change_{model_name}'
        elif action == 'destroy':
            perm_name = f'delete_{model_name}'
        else:
            return False
            
        required_perm = f'{app_label}.{perm_name}'
            
        return request.user.has_perm(required_perm)
