import uuid
import logging
from django.http import JsonResponse
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
        token_company = set_current_company(None)
        token_branch = set_current_branch(None)
        token_role = set_current_role(None)
        try:
            return self.get_response(request)
        finally:
            reset_current_role(token_role)
            reset_current_branch(token_branch)
            reset_current_company(token_company)
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

        if getattr(user, 'is_superuser', False):
            return self._with_context(request, None, None, None)

        branch_id = request.headers.get('X-Branch-ID')
        company_id = request.headers.get('X-Company-ID')

        from core.models import Role, UserMembership

        memberships = list(UserMembership.unscoped_objects.filter(
            user=user,
            is_active=True,
        ).select_related('company', 'branch'))

        if not memberships:
            return JsonResponse(
                {"detail": "Active company/branch context required."},
                status=400,
            )

        branch_roles = {
            Role.BRANCH_ADMIN,
            Role.BOOKING_USER,
            Role.DELIVERY_USER,
            Role.ACCOUNTANT,
            Role.VIEWER,
        }

        candidates = memberships
        if company_id:
            candidates = [membership for membership in candidates if str(membership.company_id) == str(company_id)]
            if not candidates:
                return JsonResponse({"detail": "Invalid active company context."}, status=400)

        if branch_id:
            candidates = [membership for membership in candidates if str(membership.branch_id) == str(branch_id)]
            if not candidates:
                return JsonResponse({"detail": "Invalid active branch context."}, status=400)
            if company_id and any(str(membership.company_id) != str(company_id) for membership in candidates):
                return JsonResponse({"detail": "Invalid active company/branch context."}, status=400)

        if not company_id and not branch_id and len(memberships) > 1:
            return JsonResponse(
                {"detail": "Active company/branch context required."},
                status=400,
            )

        if len(candidates) > 1:
            company_level = [membership for membership in candidates if membership.branch_id is None]
            branch_level = [membership for membership in candidates if membership.branch_id is not None]

            if branch_id and branch_level:
                candidates = branch_level
            elif len(company_level) == 1 and not branch_level:
                candidates = company_level
            elif company_id and len(branch_level) == 1:
                candidates = branch_level
            else:
                return JsonResponse(
                    {"detail": "Active company/branch context required."},
                    status=400,
                )

        active_membership = candidates[0]

        if active_membership.role in branch_roles and active_membership.branch_id is None:
            return JsonResponse(
                {"detail": "Active branch context required for this role."},
                status=400,
            )

        return self._with_context(
            request,
            active_membership.company,
            active_membership.branch,
            active_membership.role,
        )

    def _with_context(self, request, company, branch, role):
        request.current_company = company
        request.current_branch = branch
        request.current_role = role

        token_company = set_current_company(getattr(request, 'current_company', None))
        token_branch = set_current_branch(getattr(request, 'current_branch', None))
        token_role = set_current_role(getattr(request, 'current_role', None))

        try:
            return self.get_response(request)
        finally:
            reset_current_company(token_company)
            reset_current_branch(token_branch)
            reset_current_role(token_role)
