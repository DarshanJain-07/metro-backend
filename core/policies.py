from django.core.exceptions import ValidationError
from django.db import models
from django.db.utils import DatabaseError, ProgrammingError

from core.models import (
    CompanyRolePermissionOverride,
    MasterScope,
    PermissionCatalog,
    PermissionScope,
    Role,
    RoleDefinition,
    RoleTemplate,
    RoleTemplatePermission,
    UserMembership,
)


DEFAULT_ROLE_DEFINITIONS = (
    {"code": Role.SUPER_ADMIN, "name": "Super Admin", "requires_office": False, "sort_order": 10},
    {"code": Role.BRANCH_ADMIN, "name": "Branch Admin", "requires_office": True, "sort_order": 20},
    {"code": Role.BOOKING_USER, "name": "Booking User", "requires_office": True, "sort_order": 30},
    {"code": Role.DELIVERY_USER, "name": "Delivery User", "requires_office": True, "sort_order": 40},
    {"code": Role.ACCOUNTANT, "name": "Accountant", "requires_office": True, "sort_order": 50},
    {"code": Role.VIEWER, "name": "Viewer", "requires_office": True, "sort_order": 60},
)

PERMISSION_CATALOG = {
    "shipment:view": ("View Shipments", "Operations", "View shipments and docket activity."),
    "shipment:create": ("Create Shipments", "Operations", "Create and book shipments."),
    "shipment:edit": ("Edit Shipments", "Operations", "Edit shipment details and cancel shipments."),
    "shipment:dispatch": ("Dispatch Shipments", "Operations", "Dispatch shipments from a branch."),
    "shipment:receive": ("Receive Shipments", "Operations", "Receive shipments and complete delivery workflows."),
    "invoice:view": ("View Invoices", "Accounting", "View invoices and ledger entries."),
    "invoice:create": ("Create Invoices", "Accounting", "Create invoices."),
    "invoice:edit": ("Edit Invoices", "Accounting", "Edit invoices."),
    "invoice:delete": ("Delete Invoices", "Accounting", "Delete invoices."),
    "invoice:generate": ("Generate Invoices", "Accounting", "Generate invoices from shipments."),
    "payment:view": ("View Payments", "Accounting", "View payment receipts."),
    "payment:create": ("Create Payments", "Accounting", "Create payment receipts."),
    "payment:edit": ("Edit Payments", "Accounting", "Edit payment receipts."),
    "payment:delete": ("Delete Payments", "Accounting", "Delete payment receipts."),
    "payment:verify": ("Verify Payments", "Accounting", "Verify bank payments."),
    "expense:view": ("View Expenses", "Accounting", "View expenses."),
    "expense:create": ("Create Expenses", "Accounting", "Create expenses."),
    "expense:edit": ("Edit Expenses", "Accounting", "Edit expenses."),
    "expense:delete": ("Delete Expenses", "Accounting", "Delete expenses."),
    "master:view": ("View Master Data", "Master Data", "View master data."),
    "master:create": ("Create Master Data", "Master Data", "Create master data."),
    "master:edit": ("Edit Master Data", "Master Data", "Edit master data."),
    "master:delete": ("Delete Master Data", "Master Data", "Delete master data."),
    "master:import": ("Import Master Data", "Master Data", "Import master data."),
    "users:view": ("View Users", "Administration", "View users and memberships."),
    "users:create": ("Create Users", "Administration", "Create users and memberships."),
    "users:edit": ("Edit Users", "Administration", "Edit users and memberships."),
    "users:delete": ("Delete Users", "Administration", "Delete users and memberships."),
    "users:reset_password": ("Reset User Passwords", "Administration", "Reset user passwords."),
    "roles:manage": ("Manage Role Permissions", "Administration", "Manage role permission overrides."),
    "reports:view": ("View Reports", "Administration", "View reports and dashboards."),
}

ROLE_PERMISSION_GRANTS = {
    Role.SUPER_ADMIN: {"*": PermissionScope.COMPANY},
    Role.BRANCH_ADMIN: {
        "shipment:view": PermissionScope.BRANCH,
        "shipment:create": PermissionScope.BRANCH,
        "shipment:edit": PermissionScope.BRANCH,
        "shipment:dispatch": PermissionScope.BRANCH,
        "shipment:receive": PermissionScope.BRANCH,
        "invoice:view": PermissionScope.BRANCH,
        "invoice:create": PermissionScope.BRANCH,
        "invoice:generate": PermissionScope.BRANCH,
        "payment:view": PermissionScope.BRANCH,
        "payment:create": PermissionScope.BRANCH,
        "payment:verify": PermissionScope.BRANCH,
        "expense:view": PermissionScope.BRANCH,
        "expense:create": PermissionScope.BRANCH,
        "expense:edit": PermissionScope.BRANCH,
        "expense:delete": PermissionScope.BRANCH,
        "master:view": PermissionScope.BRANCH,
        "master:create": PermissionScope.BRANCH,
        "master:edit": PermissionScope.BRANCH,
        "master:delete": PermissionScope.BRANCH,
        "master:import": PermissionScope.BRANCH,
        "users:view": PermissionScope.BRANCH,
        "users:create": PermissionScope.BRANCH,
        "users:edit": PermissionScope.BRANCH,
        "users:delete": PermissionScope.BRANCH,
        "users:reset_password": PermissionScope.BRANCH,
        "roles:manage": PermissionScope.BRANCH,
        "reports:view": PermissionScope.BRANCH,
    },
    Role.BOOKING_USER: {
        "shipment:view": PermissionScope.BRANCH,
        "shipment:create": PermissionScope.BRANCH,
        "master:view": PermissionScope.BRANCH,
        "master:create": PermissionScope.BRANCH,
    },
    Role.DELIVERY_USER: {
        "shipment:receive": PermissionScope.BRANCH,
    },
    Role.ACCOUNTANT: {
        "invoice:view": PermissionScope.BRANCH,
        "invoice:create": PermissionScope.BRANCH,
        "invoice:edit": PermissionScope.BRANCH,
        "invoice:generate": PermissionScope.BRANCH,
        "payment:view": PermissionScope.BRANCH,
        "payment:create": PermissionScope.BRANCH,
        "payment:edit": PermissionScope.BRANCH,
        "payment:verify": PermissionScope.BRANCH,
        "expense:view": PermissionScope.BRANCH,
        "expense:create": PermissionScope.BRANCH,
        "expense:edit": PermissionScope.BRANCH,
        "expense:delete": PermissionScope.BRANCH,
    },
    Role.VIEWER: {
        "shipment:view": PermissionScope.BRANCH,
        "invoice:view": PermissionScope.BRANCH,
        "payment:view": PermissionScope.BRANCH,
        "expense:view": PermissionScope.BRANCH,
        "master:view": PermissionScope.BRANCH,
        "users:view": PermissionScope.BRANCH,
        "reports:view": PermissionScope.BRANCH,
    },
}

ROLE_ACTIONS = {role: set(grants.keys()) for role, grants in ROLE_PERMISSION_GRANTS.items()}

ACTION_ALIASES = {
    "shipment:book": "shipment:create",
    "shipment:update": "shipment:edit",
    "shipment:assign_delivery": "shipment:receive",
    "shipment:deliver": "shipment:receive",
    "shipment:cancel": "shipment:edit",
    "billing:view": "invoice:view",
    "billing:create": "invoice:generate",
    "office:manage": "master:edit",
    "users:manage": "roles:manage",
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


def normalize_action(action):
    return ACTION_ALIASES.get(action, action)


def default_role_grants(role):
    return dict(ROLE_PERMISSION_GRANTS.get(role, {}))


def current_role_template(role):
    template = RoleTemplate.objects.filter(role=role, is_active=True).order_by("-revision").first()
    if template:
        return template
    return None


def role_template_revision(role):
    template = current_role_template(role)
    return template.revision if template else 1


def template_role_grants(role):
    if "*" in default_role_grants(role):
        return default_role_grants(role)
    template = current_role_template(role)
    if not template:
        return default_role_grants(role)
    grants = {}
    for grant in template.permission_grants.select_related("permission"):
        if grant.permission.is_active:
            grants[grant.permission.code] = grant.scope
    return grants


def effective_role_grants(company, role):
    grants = template_role_grants(role)
    if company:
        overrides = CompanyRolePermissionOverride.unscoped_objects.filter(
            company=company,
            role=role,
            permission__is_active=True,
            is_active=True,
        ).select_related("permission")
        for override in overrides:
            code = override.permission.code
            if override.enabled:
                grants[code] = override.scope
            else:
                grants.pop(code, None)
    return grants


def effective_membership_grants(membership):
    return effective_role_grants(membership.company, membership.role)


def effective_permissions_for_user(user, company=None):
    if not user or not user.is_authenticated:
        return {}
    if user.is_superuser:
        return {"*": PermissionScope.ALL}

    permissions = {}
    for membership in user_memberships(user):
        if company and membership.company_id != company.id:
            continue
        for code, scope in effective_membership_grants(membership).items():
            if code == "*":
                permissions[code] = scope
                continue
            permissions.setdefault(code, scope)
            if scope_rank(scope) > scope_rank(permissions[code]):
                permissions[code] = scope
    return permissions


def scope_rank(scope):
    return {
        PermissionScope.OWN: 1,
        PermissionScope.BRANCH: 2,
        PermissionScope.REGION: 2,
        PermissionScope.COMPANY: 3,
        PermissionScope.ALL: 4,
    }.get(scope, 0)


def permission_scope_allows(scope, membership, office=None, resource=None):
    if scope in (PermissionScope.ALL, PermissionScope.COMPANY):
        return True
    if scope == PermissionScope.OWN:
        owner_id = getattr(resource, "created_by_id", None) or getattr(resource, "user_id", None)
        return bool(owner_id and membership and owner_id == membership.user_id)
    if scope in (PermissionScope.BRANCH, PermissionScope.REGION):
        if not office:
            return bool(membership.office_id is None)
        return membership.office_id == office.id
    return False


def seed_permission_catalog():
    for code, (name, group, description) in PERMISSION_CATALOG.items():
        PermissionCatalog.objects.update_or_create(
            code=code,
            defaults={"name": name, "group": group, "description": description, "is_active": True},
        )


def seed_role_definitions():
    for definition in DEFAULT_ROLE_DEFINITIONS:
        try:
            RoleDefinition.objects.get_or_create(
                code=definition["code"],
                defaults={
                    "name": definition["name"],
                    "requires_office": definition["requires_office"],
                    "sort_order": definition["sort_order"],
                    "is_active": True,
                },
            )
        except (DatabaseError, ProgrammingError):
            return


def active_role_definitions():
    seed_role_definitions()
    try:
        return RoleDefinition.objects.filter(is_active=True).order_by("sort_order", "name")
    except (DatabaseError, ProgrammingError):
        return []


def default_role_definition_payloads():
    return [
        {
            "id": None,
            "code": definition["code"],
            "name": definition["name"],
            "description": "",
            "requires_office": definition["requires_office"],
            "is_active": True,
            "sort_order": definition["sort_order"],
        }
        for definition in DEFAULT_ROLE_DEFINITIONS
    ]


def role_definition(role):
    seed_role_definitions()
    try:
        return RoleDefinition.objects.filter(code=role, is_active=True).first()
    except (DatabaseError, ProgrammingError):
        return None


def role_requires_office(role):
    definition = role_definition(role)
    if definition is not None:
        return definition.requires_office
    default_definition = next(
        (item for item in DEFAULT_ROLE_DEFINITIONS if item["code"] == role),
        None,
    )
    return True if default_definition is None else default_definition["requires_office"]


def seed_role_templates(revision=1):
    seed_role_definitions()
    seed_permission_catalog()
    for role, grants in ROLE_PERMISSION_GRANTS.items():
        if "*" in grants:
            continue
        template, _ = RoleTemplate.objects.update_or_create(
            role=role,
            revision=revision,
            defaults={"name": role_definition(role).name if role_definition(role) else role, "is_active": True},
        )
        for code, scope in grants.items():
            permission = PermissionCatalog.objects.filter(code=code).first()
            if permission:
                RoleTemplatePermission.objects.update_or_create(
                    template=template,
                    permission=permission,
                    defaults={"scope": scope},
                )


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
    action = normalize_action(action)

    for membership in user_memberships(user):
        if company and membership.company_id != company.id:
            continue
        grants = effective_membership_grants(membership)
        if "*" in grants:
            return permission_scope_allows(grants["*"], membership, office=office, resource=resource)
        scope = grants.get(action)
        if scope and permission_scope_allows(scope, membership, office=office, resource=resource):
            return True
    return False


def can_manage_master_data(user, company):
    if can_manage_company(user, company):
        return True
    return bool(company and can(user, "master:edit", company=company))


def active_master_scope(role=None, office=None):
    if office and role_requires_office(role):
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
    if user and user.is_superuser:
        return models.Q()
    if can_manage_company(user, company):
        return models.Q(scope_type=MasterScope.COMPANY)

    branch_scope_ids = [str(office_id) for office_id in active_office_ids(user, company)]
    return models.Q(scope_type=MasterScope.COMPANY) | models.Q(
        scope_type=MasterScope.BRANCH,
        scope_id__in=branch_scope_ids,
    )


def can_manage_office_master_data(user, office):
    return can(user, "master:edit", company=office.company, office=office) or can_manage_company(user, office.company)


def can_manage_company(user, company):
    if user and user.is_superuser:
        return True
    if not company:
        return False
    return can(user, "*", company=company)


def can_manage_office(user, office):
    if can_manage_company(user, office.company):
        return True
    return can(user, "master:edit", company=office.company, office=office)


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
    return can(user, "shipment:create", company=shipment.company, office=shipment.origin_office, resource=shipment)


def can_edit_shipment(user, shipment):
    if can_manage_company(user, shipment.company):
        return True
    if shipment.status in ["DELIVERED", "CANCELLED"]:
        return False
    return can(user, "shipment:edit", company=shipment.company, office=shipment.origin_office, resource=shipment)


def can_dispatch_shipment(user, shipment, office=None):
    office = office or shipment.origin_office
    return can(user, "shipment:dispatch", company=shipment.company, office=office)


def can_cancel_shipment(user, shipment):
    return can(user, "shipment:edit", company=shipment.company, office=shipment.origin_office, resource=shipment)


def can_receive_shipment(user, shipment, office):
    return can(user, "shipment:receive", company=shipment.company, office=office)


def can_assign_delivery(user, shipment):
    return can(user, "shipment:receive", company=shipment.company, office=shipment.destination_office, resource=shipment)


def can_mark_delivered(user, shipment):
    if can(user, "shipment:receive", company=shipment.company, office=shipment.destination_office, resource=shipment):
        return True
    return shipment.delivery_assignments.filter(delivery_user=user, status="ASSIGNED").exists()


def can_manage_billing(user, company_or_office):
    company = getattr(company_or_office, "company", company_or_office)
    if hasattr(company_or_office, "company"):
        return can(user, "invoice:generate", company=company, office=company_or_office)
    return can(user, "invoice:generate", company=company)


def can_verify_payment(user, payment):
    return can_manage_billing(user, payment.office)


def can_manage_users(user, company):
    return can(user, "roles:manage", company=company)
