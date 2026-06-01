import uuid
import logging
from core.request_context import (
    get_request_id,
    reset_current_request,
    reset_primary_requested,
    reset_request_id,
    reset_request_method,
    set_current_request,
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
