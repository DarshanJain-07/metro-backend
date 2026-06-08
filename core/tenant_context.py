from dataclasses import dataclass

from django.core.exceptions import ValidationError

from core.models import Role, UserMembership


BRANCH_SCOPED_ROLES = {
    Role.BRANCH_ADMIN,
    Role.BOOKING_USER,
    Role.DELIVERY_USER,
    Role.ACCOUNTANT,
    Role.VIEWER,
}


@dataclass
class ActiveTenantContext:
    company: object
    branch: object
    role: str


def resolve_active_tenant_context(user, company_id=None, branch_id=None):
    if getattr(user, 'is_superuser', False):
        return ActiveTenantContext(company=None, branch=None, role=None)

    memberships = list(UserMembership.unscoped_objects.filter(
        user=user,
        is_active=True,
    ).select_related('company', 'branch'))

    if not memberships:
        raise ValidationError("Active company/branch context required.")

    candidates = memberships
    if company_id:
        candidates = [membership for membership in candidates if str(membership.company_id) == str(company_id)]
        if not candidates:
            raise ValidationError("Invalid active company context.")

    if branch_id:
        candidates = [membership for membership in candidates if str(membership.branch_id) == str(branch_id)]
        if not candidates:
            raise ValidationError("Invalid active branch context.")

    if not company_id and not branch_id and len(memberships) > 1:
        raise ValidationError("Active company/branch context required.")

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
            raise ValidationError("Active company/branch context required.")

    active_membership = candidates[0]
    if active_membership.role in BRANCH_SCOPED_ROLES and active_membership.branch_id is None:
        raise ValidationError("Active branch context required for this role.")

    return ActiveTenantContext(
        company=active_membership.company,
        branch=active_membership.branch,
        role=active_membership.role,
    )
