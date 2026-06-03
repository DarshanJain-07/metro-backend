from core.models import Role, UserMembership

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

def can_manage_company(user, company):
    if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
        return True
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

def can_update_docket_status(user, docket, target_status):
    # Determine branch based on if it's destination or origin (simplified for now to destination or origin)
    branch = getattr(docket, 'destination_branch', None) or docket.origin_branch
    if can_manage_company(user, branch.company):
        return True
    return has_role(user, company=branch.company, branch=branch, roles=[Role.BRANCH_ADMIN, Role.BOOKING_USER, Role.DELIVERY_USER])

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
    return has_role(user, company=company, roles=[Role.ACCOUNTANT])
