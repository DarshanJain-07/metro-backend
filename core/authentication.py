from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.request_context import set_current_branch, set_current_company, set_current_role
from core.tenant_context import resolve_active_tenant_context


class ActiveContextJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result
        try:
            context = resolve_active_tenant_context(
                user,
                company_id=request.headers.get('X-Company-ID'),
                branch_id=request.headers.get('X-Branch-ID'),
            )
        except DjangoValidationError as exc:
            detail = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)
            raise exceptions.ParseError(detail)

        request.current_company = context.company
        request.current_branch = context.branch
        request.current_role = context.role
        set_current_company(context.company)
        set_current_branch(context.branch)
        set_current_role(context.role)
        return user, token
