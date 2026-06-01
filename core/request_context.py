import contextvars

_current_user = contextvars.ContextVar('current_user', default=None)
_current_company = contextvars.ContextVar('current_company', default=None)
_current_request = contextvars.ContextVar('current_request', default=None)
_request_method = contextvars.ContextVar('request_method', default=None)
_use_primary = contextvars.ContextVar('use_primary', default=False)
_request_id = contextvars.ContextVar('request_id', default=None)


def get_current_request():
    return _current_request.get()


def set_current_request(request):
    return _current_request.set(request)


def reset_current_request(token):
    _current_request.reset(token)


def get_current_user():
    user = _current_user.get()
    if user is not None:
        return user

    request = get_current_request()
    if request is None:
        return None

    return getattr(request, 'user', None)


def set_current_user(user):
    return _current_user.set(user)


def reset_current_user(token):
    _current_user.reset(token)


def get_current_company():
    company = _current_company.get()
    if company is not None:
        return company

    user = get_current_user()
    if user and getattr(user, 'is_authenticated', False):
        return getattr(user, 'company', None)

    return None


def set_current_company(company):
    return _current_company.set(company)


def reset_current_company(token):
    _current_company.reset(token)


def get_request_method():
    return _request_method.get()


def set_request_method(method):
    return _request_method.set(method)


def reset_request_method(token):
    _request_method.reset(token)


def is_primary_requested():
    return _use_primary.get()


def set_primary_requested(use_primary):
    return _use_primary.set(use_primary)


def reset_primary_requested(token):
    _use_primary.reset(token)


def get_request_id():
    return _request_id.get()


def set_request_id(request_id):
    return _request_id.set(request_id)


def reset_request_id(token):
    _request_id.reset(token)
