import contextvars

_current_user = contextvars.ContextVar('current_user', default=None)
_current_company = contextvars.ContextVar('current_company', default=None)
_current_branch = contextvars.ContextVar('current_branch', default=None)
_current_role = contextvars.ContextVar('current_role', default=None)
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


def get_current_company(user=None):
    company = _current_company.get()
    if company is not None:
        return company

    request = get_current_request()
    if request:
        company = getattr(request, 'current_company', None)
        if company:
            return company

    if user is None:
        user = get_current_user()

    if user and getattr(user, 'is_authenticated', False):
        from core.models import UserMembership
        company_ids = list(
            UserMembership.unscoped_objects.filter(user=user, is_active=True)
            .values_list('company_id', flat=True)
            .distinct()
        )
        if len(company_ids) == 1:
            from core.models import Company
            return Company.objects.filter(pk=company_ids[0]).first()

    return None


def set_current_company(company):
    return _current_company.set(company)


def reset_current_company(token):
    _current_company.reset(token)


def get_current_branch(user=None):
    branch = _current_branch.get()
    if branch is not None:
        return branch

    request = get_current_request()
    if request:
        branch = getattr(request, 'current_branch', None)
        if branch:
            return branch

    if user is None:
        user = get_current_user()

    if user and getattr(user, 'is_authenticated', False):
        from core.models import UserMembership
        branch_ids = list(
            UserMembership.unscoped_objects.filter(user=user, is_active=True, branch__isnull=False)
            .values_list('branch_id', flat=True)
            .distinct()
        )
        if len(branch_ids) == 1:
            from core.models import Branch
            return Branch.objects.filter(pk=branch_ids[0]).first()

    return None


def set_current_branch(branch):
    return _current_branch.set(branch)


def reset_current_branch(token):
    _current_branch.reset(token)


def get_current_role():
    return _current_role.get()


def set_current_role(role):
    return _current_role.set(role)


def reset_current_role(token):
    _current_role.reset(token)


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
