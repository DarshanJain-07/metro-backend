from django.core.exceptions import ValidationError as DjangoValidationError
from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from core.request_context import set_current_company, set_current_office, set_current_role
from core.tenant_context import resolve_active_tenant_context
from authentication.workos_service import (
    WorkOSConfigurationError,
    WorkOSSessionInvalid,
    authenticate_workos_session_cookie,
)


def _apply_active_context(request, user):
    try:
        context = resolve_active_tenant_context(
            user,
            company_id=request.headers.get("X-Company-ID"),
            office_id=request.headers.get("X-Office-ID"),
        )
    except DjangoValidationError as exc:
        detail = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        raise exceptions.ParseError(detail)

    request.current_company = context.company
    request.current_office = context.office
    request.current_role = context.role
    set_current_company(context.company)
    set_current_office(context.office)
    set_current_role(context.role)


class ActiveContextWorkOSSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        session_cookie = (
            request.headers.get(settings.WORKOS_SESSION_HEADER)
            or request.COOKIES.get(settings.WORKOS_SESSION_COOKIE_NAME)
        )
        if not session_cookie:
            return None

        try:
            result = authenticate_workos_session_cookie(session_cookie)
        except WorkOSConfigurationError as exc:
            raise exceptions.AuthenticationFailed("Authentication is not configured.") from exc
        except WorkOSSessionInvalid as exc:
            raise exceptions.AuthenticationFailed("Authentication session expired.") from exc

        user = result.user
        request.workos_session = result.session
        request.workos_session_id = result.session.session_id
        if result.sealed_session:
            request.workos_refreshed_session = result.sealed_session

        _apply_active_context(request, user)
        return user, result.workos_session
