from dataclasses import dataclass

from django.core.exceptions import ValidationError

from core.models import Role, UserMembership


OFFICE_SCOPED_ROLES = {
    Role.OFFICE_ADMIN,
    Role.BOOKING_USER,
    Role.DELIVERY_USER,
    Role.ACCOUNTANT,
    Role.VIEWER,
}


@dataclass
class ActiveTenantContext:
    company: object
    office: object
    role: str


def resolve_active_tenant_context(user, company_id=None, office_id=None):
    if getattr(user, "is_superuser", False):
        return ActiveTenantContext(company=None, office=None, role=None)

    memberships = list(
        UserMembership.unscoped_objects.filter(user=user, is_active=True).select_related("company", "office")
    )
    if not memberships:
        raise ValidationError("Active company/office context required.")

    candidates = memberships
    if company_id:
        candidates = [membership for membership in candidates if str(membership.company_id) == str(company_id)]
        if not candidates:
            raise ValidationError("Invalid active company context.")

    if office_id:
        candidates = [membership for membership in candidates if str(membership.office_id) == str(office_id)]
        if not candidates:
            raise ValidationError("Invalid active office context.")

    if not company_id and not office_id and len(memberships) > 1:
        raise ValidationError("Active company/office context required.")

    if len(candidates) > 1:
        company_level = [membership for membership in candidates if membership.office_id is None]
        office_level = [membership for membership in candidates if membership.office_id is not None]
        if office_id and office_level:
            candidates = office_level
        elif len(company_level) == 1 and not office_level:
            candidates = company_level
        elif company_id and len(office_level) == 1:
            candidates = office_level
        else:
            raise ValidationError("Active company/office context required.")

    active_membership = candidates[0]
    if active_membership.role in OFFICE_SCOPED_ROLES and active_membership.office_id is None:
        raise ValidationError("Active office context required for this role.")

    return ActiveTenantContext(
        company=active_membership.company,
        office=active_membership.office,
        role=active_membership.role,
    )
