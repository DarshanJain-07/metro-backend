from django.core.exceptions import ValidationError

from django.db import models

from core.models import MasterScope, Role, UserMembership


COMPANY_ROLES = (Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN)
OFFICE_ROLES = (
    Role.BRANCH_ADMIN,
    Role.BOOKING_USER,
    Role.DELIVERY_USER,
    Role.ACCOUNTANT,
    Role.VIEWER,
)

ROLE_ACTIONS = {
    Role.PLATFORM_ADMIN: {"*"},
    Role.CLIENT_SUPER_ADMIN: {"*"},
    Role.BRANCH_ADMIN: {
        "office:manage",
        "shipment:book",
        "shipment:create",
        "shipment:update",
        "shipment:dispatch",
        "shipment:receive",
        "shipment:assign_delivery",
        "shipment:deliver",
        "shipment:cancel",
        "shipment:view",
        "billing:create",
        "billing:view",
        "reports:view",
        "users:manage",
    },
    Role.BOOKING_USER: {
        "shipment:create",
        "shipment:book",
        "shipment:view",
    },
    Role.DELIVERY_USER: {
        "shipment:receive",
        "shipment:deliver",
    },
    Role.ACCOUNTANT: {
        "billing:create",
        "billing:view",
    },
    Role.VIEWER: {"shipment:view", "reports:view"},
}


def user_memberships(user):
    if not user or not user.is_authenticated:
        return []

    from core.request_context import get_current_request

    request = get_current_request()
    cache_key = f"_user_memberships_{user.id}"
    memberships = getattr(request, cache_key, None) if request else None

    if memberships is None:
        memberships = list(
            UserMembership.unscoped_objects.filter(user=user, is_active=True).select_related("company", "office")
        )
        if request:
            setattr(request, cache_key, memberships)

    return memberships


def has_role(user, company=None, office=None, roles=None):
    if not user or not user.is_authenticated or not roles:
        return False

    for membership in user_memberships(user):
        if company and membership.company_id != company.id:
            continue
        if office and membership.office_id != office.id:
            continue
        if membership.role in roles:
            return True
    return False


def active_office_ids(user, company):
    if not user or not user.is_authenticated or not company:
        return []

    from core.request_context import get_current_request

    request = get_current_request()

    memberships_cache_key = f"_user_memberships_{user.id}"
    if request and hasattr(request, memberships_cache_key):
        memberships = getattr(request, memberships_cache_key)
        return [
            m.office_id for m in memberships
            if m.company_id == company.id and m.office_id is not None
        ]

    cache_key = f"_active_office_ids_{company.id}"
    if request and hasattr(request, cache_key):
        return getattr(request, cache_key)

    office_ids = list(
        UserMembership.unscoped_objects.filter(
            user=user,
            company=company,
            office__isnull=False,
            is_active=True,
        ).values_list("office_id", flat=True)
    )

    if request:
        setattr(request, cache_key, office_ids)

    return office_ids


def require_active_company(request):
    from core.request_context import get_current_company

    company = get_current_company()
    if not company:
        raise ValidationError("Active company context required.")
    return company


def require_active_office(request):
    from core.request_context import get_current_office

    office = get_current_office()
    if not office:
        raise ValidationError("Active office context required.")
    return office


def validate_company_object(obj, company, field_name="detail"):
    obj_company = getattr(obj, "company", None)
    if obj_company is not None and obj_company != company:
        raise ValidationError({field_name: "Object does not belong to the active company."})
    return obj


def validate_office_object(office, company, field_name="office"):
    if office.company != company:
        raise ValidationError({field_name: "Office does not belong to the active company."})
    return office


def can(user, action, company=None, office=None, resource=None):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    for membership in user_memberships(user):
        if company and membership.company_id != company.id:
            continue
        if office and membership.office_id and membership.office_id != office.id:
            continue
        if office and membership.office_id is None and membership.role not in COMPANY_ROLES:
            continue
        actions = ROLE_ACTIONS.get(membership.role, set())
        if "*" in actions or action in actions:
            return True
    return False


def can_manage_master_data(user, company):
    if can_manage_company(user, company):
        return True
    return bool(company and can(user, "office:manage", company=company))


def active_master_scope(role=None, office=None):
    if office and role in OFFICE_ROLES:
        return MasterScope.BRANCH, str(office.id)
    return MasterScope.COMPANY, None


def assign_master_scope(instance, role=None, office=None):
    if not hasattr(instance, "scope_type"):
        return instance
    scope_type, scope_id = active_master_scope(role=role, office=office)
    instance.scope_type = scope_type
    instance.scope_id = scope_id
    return instance


def visible_master_scope_filter(user, company):
    if not company:
        return models.Q(pk__in=[])
    if user and (user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN])):
        return models.Q()
    if has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN]):
        return models.Q(scope_type=MasterScope.COMPANY)

    branch_scope_ids = [str(office_id) for office_id in active_office_ids(user, company)]
    return models.Q(scope_type=MasterScope.COMPANY) | models.Q(
        scope_type=MasterScope.BRANCH,
        scope_id__in=branch_scope_ids,
    )


def can_manage_office_master_data(user, office):
    return can(user, "office:manage", company=office.company, office=office) or can_manage_company(user, office.company)


def can_manage_company(user, company):
    if user and (user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN])):
        return True
    if not company:
        return False
    return has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN])


def can_manage_office(user, office):
    if can_manage_company(user, office.company):
        return True
    return can(user, "office:manage", company=office.company, office=office)


def shipment_participates_at_office(shipment, office):
    if not shipment or not office:
        return False
    if shipment.origin_office_id == office.id or shipment.destination_office_id == office.id:
        return True
    return shipment.events.filter(office=office).exists()


def can_view_shipment(user, shipment):
    if can_manage_company(user, shipment.company):
        return True
    for office_id in active_office_ids(user, shipment.company):
        if shipment.origin_office_id == office_id or shipment.destination_office_id == office_id:
            return True
    return shipment.events.filter(office_id__in=active_office_ids(user, shipment.company)).exists()


def can_create_shipment(user, office):
    if can_manage_company(user, office.company):
        return True
    return can(user, "shipment:create", company=office.company, office=office)


def can_book_shipment(user, shipment):
    return can(user, "shipment:book", company=shipment.company, office=shipment.origin_office)


def can_edit_shipment(user, shipment):
    if can_manage_company(user, shipment.company):
        return True
    if shipment.status in ["DELIVERED", "CANCELLED"]:
        return False
    return can(user, "shipment:update", company=shipment.company, office=shipment.origin_office)


def can_dispatch_shipment(user, shipment, office=None):
    office = office or shipment.origin_office
    return can(user, "shipment:dispatch", company=shipment.company, office=office)


def can_cancel_shipment(user, shipment):
    return can(user, "shipment:cancel", company=shipment.company, office=shipment.origin_office)


def can_receive_shipment(user, shipment, office):
    return can(user, "shipment:receive", company=shipment.company, office=office)


def can_assign_delivery(user, shipment):
    return can(user, "shipment:assign_delivery", company=shipment.company, office=shipment.destination_office)


def can_mark_delivered(user, shipment):
    if can(user, "shipment:deliver", company=shipment.company, office=shipment.destination_office):
        return True
    return shipment.delivery_assignments.filter(delivery_user=user, status="ASSIGNED").exists()


def can_manage_billing(user, company_or_office):
    company = getattr(company_or_office, "company", company_or_office)
    if hasattr(company_or_office, "company"):
        return can(user, "billing:create", company=company, office=company_or_office)
    return can(user, "billing:create", company=company)


def can_verify_payment(user, payment):
    return can_manage_billing(user, payment.office)


def can_manage_users(user, company):
    return can(user, "users:manage", company=company)
