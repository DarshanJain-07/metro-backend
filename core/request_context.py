import contextvars

_current_user = contextvars.ContextVar("current_user", default=None)
_current_company = contextvars.ContextVar("current_company", default=None)
_current_office = contextvars.ContextVar("current_office", default=None)
_current_role = contextvars.ContextVar("current_role", default=None)
_current_request = contextvars.ContextVar("current_request", default=None)
_request_method = contextvars.ContextVar("request_method", default=None)
_use_primary = contextvars.ContextVar("use_primary", default=False)
_request_id = contextvars.ContextVar("request_id", default=None)


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
    return getattr(request, "user", None) if request else None


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
        company = getattr(request, "current_company", None)
        if company:
            return company

    if user is None:
        user = get_current_user()

    if user and getattr(user, "is_authenticated", False):
        from core.models import Company, UserMembership

        company_ids = list(
            UserMembership.unscoped_objects.filter(user=user, is_active=True)
            .values_list("company_id", flat=True)
            .distinct()
        )
        if len(company_ids) == 1:
            return Company.objects.filter(pk=company_ids[0]).first()

    return None


def set_current_company(company):
    return _current_company.set(company)


def reset_current_company(token):
    _current_company.reset(token)


def get_current_office(user=None):
    office = _current_office.get()
    if office is not None:
        return office

    request = get_current_request()
    if request:
        if hasattr(request, "current_office"):
            return getattr(request, "current_office")

    if user is None:
        user = get_current_user()

    if user and getattr(user, "is_authenticated", False):
        from core.models import CompanyOffice, UserMembership

        company = get_current_company(user)
        memberships = UserMembership.unscoped_objects.filter(user=user, is_active=True, office__isnull=False)
        if company:
            memberships = memberships.filter(company=company)
        office_ids = list(
            memberships.values_list("office_id", flat=True).distinct()
        )
        if len(office_ids) == 1:
            return CompanyOffice.objects.filter(pk=office_ids[0]).first()

    return None


def set_current_office(office):
    return _current_office.set(office)


def reset_current_office(token):
    _current_office.reset(token)


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
