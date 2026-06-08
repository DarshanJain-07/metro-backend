from django.core.exceptions import ValidationError

from core.models import Role, UserMembership


COMPANY_ROLES = (Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN)
BRANCH_ROLES = (
    Role.BRANCH_ADMIN,
    Role.BOOKING_USER,
    Role.DELIVERY_USER,
    Role.ACCOUNTANT,
    Role.VIEWER,
)


def has_role(user, company=None, branch=None, roles=None):
    if not user.is_authenticated:
        return False
    if not roles:
        return False
        
    qs = UserMembership.unscoped_objects.filter(user=user, is_active=True, role__in=roles)
    if company:
        qs = qs.filter(company=company)
    if branch:
        qs = qs.filter(branch=branch)
    return qs.exists()


def active_branch_ids(user, company):
    if not user or not user.is_authenticated or not company:
        return []
    return list(UserMembership.unscoped_objects.filter(
        user=user,
        company=company,
        branch__isnull=False,
        is_active=True,
    ).values_list('branch_id', flat=True))


def require_active_company(request):
    from core.request_context import get_current_company

    company = get_current_company()
    if not company:
        raise ValidationError("Active company context required.")
    return company


def require_active_branch(request):
    from core.request_context import get_current_branch

    branch = get_current_branch()
    if not branch:
        raise ValidationError("Active branch context required.")
    return branch


def validate_company_object(obj, company, field_name='detail'):
    obj_company = getattr(obj, 'company', None)
    if obj_company is not None and obj_company != company:
        raise ValidationError({field_name: "Object does not belong to the active company."})
    return obj


def validate_branch_object(branch, company, field_name='branch'):
    if branch.company != company:
        raise ValidationError({field_name: "Branch does not belong to the active company."})
    return branch


def can_manage_master_data(user, company):
    return can_manage_company(user, company)


def can_manage_branch_master_data(user, branch):
    return can_manage_branch(user, branch)


def can_manage_company(user, company):
    if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
        return True
    if not company:
        return False
    return has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN])

def can_manage_branch(user, branch):
    if can_manage_company(user, branch.company):
        return True
    return has_role(user, company=branch.company, branch=branch, roles=[Role.BRANCH_ADMIN])

def can_view_branch_data(user, branch):
    if can_manage_branch(user, branch):
        return True
    # If the user has any active membership for this branch
    if has_role(user, company=branch.company, branch=branch, roles=[
        Role.BRANCH_ADMIN, Role.BOOKING_USER, Role.DELIVERY_USER, Role.ACCOUNTANT, Role.VIEWER
    ]):
        return True
    # Or if the user has an overarching role
    return has_role(user, company=branch.company, roles=[
        Role.CLIENT_SUPER_ADMIN, Role.ACCOUNTANT, Role.VIEWER
    ])

def can_create_docket(user, branch):
    if can_manage_company(user, branch.company):
        return True
    return has_role(user, company=branch.company, branch=branch, roles=[Role.BRANCH_ADMIN, Role.BOOKING_USER])

def can_edit_docket(user, docket):
    if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
        return True
    
    company = docket.company
    if has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN]):
        return True

    # Terminal statuses are locked for everyone except super admins
    if docket.status in ['DELIVERED', 'CANCELLED']:
        return False

    branch = docket.origin_branch
    
    # Branch admin can edit if they belong to the origin branch
    if has_role(user, company=company, branch=branch, roles=[Role.BRANCH_ADMIN]):
        return True
        
    # Booking user can edit ONLY DRAFT or BOOKED dockets at their origin branch
    if docket.status in ['DRAFT', 'BOOKED']:
        if has_role(user, company=company, branch=branch, roles=[Role.BOOKING_USER]):
            return True
            
    return False

def can_book_docket(user, docket):
    if can_manage_company(user, docket.company):
        return True
    return has_role(user, company=docket.company, branch=docket.origin_branch, roles=[Role.BRANCH_ADMIN, Role.BOOKING_USER])


def can_receive_incoming_load(user, docket):
    if can_manage_company(user, docket.company):
        return True
    return has_role(user, company=docket.company, branch=docket.destination_branch, roles=[Role.BRANCH_ADMIN, Role.BOOKING_USER])


def can_assign_delivery(user, docket):
    if can_manage_company(user, docket.company):
        return True
    return has_role(user, company=docket.company, branch=docket.destination_branch, roles=[Role.BRANCH_ADMIN])


def can_mark_delivered(user, docket):
    if can_manage_company(user, docket.company):
        return True
    if has_role(user, company=docket.company, branch=docket.destination_branch, roles=[Role.BRANCH_ADMIN]):
        return True
    return docket.delivery_assignments.filter(
        delivery_user=user,
        status='ASSIGNED',
    ).exists()


def can_update_docket_status(user, docket, target_status):
    if target_status in ['BOOKED', 'IN_TRANSIT', 'CANCELLED']:
        return can_book_docket(user, docket)
    if target_status == 'INCOMING':
        return can_receive_incoming_load(user, docket)
    if target_status == 'DELIVERED':
        return can_mark_delivered(user, docket)
    return False

def can_adjust_rates(user, branch):
    if can_manage_company(user, branch.company):
        return True
    return has_role(user, company=branch.company, branch=branch, roles=[Role.BRANCH_ADMIN])

def can_manage_billing(user, company_or_branch):
    if hasattr(company_or_branch, 'company'): # It's a branch
        company = company_or_branch.company
    else:
        company = company_or_branch
    if can_manage_company(user, company):
        return True
    if hasattr(company_or_branch, 'company'):
        return has_role(user, company=company, branch=company_or_branch, roles=[Role.ACCOUNTANT])
    return has_role(user, company=company, roles=[Role.ACCOUNTANT])


def can_verify_payment(user, payment):
    return can_manage_billing(user, payment.branch)


def can_manage_users(user, company):
    return can_manage_company(user, company)
