import uuid
import logging
from core.request_context import (
    get_request_id,
    reset_current_branch,
    reset_current_company,
    reset_current_request,
    reset_current_role,
    reset_primary_requested,
    reset_request_id,
    reset_request_method,
    set_current_branch,
    set_current_company,
    set_current_request,
    set_current_role,
    set_primary_requested,
    set_request_id,
    set_request_method,
)

logger = logging.getLogger(__name__)


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
            response['X-Request-ID'] = request_id
        finally:
            reset_request_id(token)
        return response


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_current_request(token)


class ExceptionLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception:
            user = getattr(request, 'user', None)
            user_id = getattr(user, 'id', None) if user and getattr(user, 'is_authenticated', False) else None
            logger.exception(
                "Unhandled request exception request_id=%s user_id=%s method=%s path=%s",
                get_request_id(),
                user_id,
                getattr(request, 'method', None),
                getattr(request, 'path', None),
            )
            raise


class RequestMethodMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token_method = set_request_method(request.method)
        # Opt-in for primary DB via header
        use_primary = request.headers.get('X-Use-Primary-DB', 'false').lower() == 'true'
        token_primary = set_primary_requested(use_primary)
        try:
            response = self.get_response(request)
        finally:
            reset_request_method(token_method)
            reset_primary_requested(token_primary)
        return response


class TenantMiddleware:
    """
    Sets the current company and branch context based on request headers or user memberships.
    Must be placed after AuthenticationMiddleware.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return self.get_response(request)

        # 1. Try to get branch/company from headers
        branch_id = request.headers.get('X-Branch-ID')
        company_id = request.headers.get('X-Company-ID')

        from core.models import UserMembership
        active_membership = None
        
        # Only check memberships if user doesn't have a direct company or if headers are provided
        # or if we want to support membership-only users.
        qs = UserMembership.unscoped_objects.filter(user=user, is_active=True).select_related('company', 'branch')
        
        if branch_id:
            active_membership = qs.filter(branch_id=branch_id).first()
        elif company_id:
            active_membership = qs.filter(company_id=company_id).first()
            
        if not active_membership:
            # Fallback: if user has a direct company, that's their default
            if getattr(user, 'company', None):
                request.current_company = user.company
                request.current_branch = user.branch
                request.current_role = None 
            else:
                # Fallback to first active membership
                active_membership = qs.first()
                
        if active_membership:
            request.current_company = active_membership.company
            request.current_branch = active_membership.branch
            request.current_role = active_membership.role

        # Set context variables for the duration of the request
        token_company = set_current_company(getattr(request, 'current_company', None))
        token_branch = set_current_branch(getattr(request, 'current_branch', None))
        token_role = set_current_role(getattr(request, 'current_role', None))
        
        try:
            return self.get_response(request)
        finally:
            reset_current_company(token_company)
            reset_current_branch(token_branch)
            reset_current_role(token_role)
