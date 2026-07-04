import logging
import secrets
import json
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import AuthAuditLog, SignupRequest
from core.models import Company, Role, RoleDefinition, UserMembership
from core.policies import role_requires_office, seed_role_templates

logger = logging.getLogger(__name__)
User = get_user_model()

GOOGLE_STATE_SALT = "metro.authentication.workos.google.state"
GOOGLE_STATE_CACHE_PREFIX = "workos:google_state:"
GOOGLE_EXCHANGE_CACHE_PREFIX = "workos:google_exchange:"
GENERIC_AUTH_ERROR = "Could not sign in. Please check your details."

SENSITIVE_METADATA_KEYS = (
    "access",
    "authorization",
    "code",
    "otp",
    "password",
    "refresh",
    "secret",
    "token",
)


class WorkOSConfigurationError(Exception):
    pass


class WorkOSAuthenticationFailed(Exception):
    def __init__(self, message=GENERIC_AUTH_ERROR, payload=None):
        super().__init__(message)
        self.payload = payload or {}


class WorkOSPendingAuthentication(Exception):
    def __init__(self, payload):
        super().__init__("Additional authentication is required.")
        self.payload = payload


class MetroAccessDenied(Exception):
    pass


def get_workos_client():
    if not settings.WORKOS_API_KEY or not settings.WORKOS_CLIENT_ID:
        raise WorkOSConfigurationError("WORKOS_API_KEY and WORKOS_CLIENT_ID are required.")

    try:
        from workos import WorkOSClient
    except ImportError as exc:
        raise WorkOSConfigurationError("The workos package is not installed.") from exc

    return WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)


def _workos_password(password):
    from workos.user_management._resource import PasswordPlaintext

    return PasswordPlaintext(password=password)


def _workos_single_role(role_slug):
    from workos.organization_membership import RoleSingle

    return RoleSingle(role_slug=role_slug)


def as_plain_data(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {
            key: as_plain_data(item) if not isinstance(item, (str, int, float, bool, type(None), list, tuple, dict)) else item
            for key, item in value.__dict__.items()
            if not key.startswith("_")
        }
    return value


def request_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR")


def request_user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")


def resolve_identifier_email(identifier):
    identifier = (identifier or "").strip()
    if "@" in identifier:
        return identifier.lower()

    user = User.objects.filter(username__iexact=identifier).only("email").first()
    if user and user.email:
        return user.email.lower()
    return identifier.lower()


def scrub_metadata(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(sensitive in lowered for sensitive in SENSITIVE_METADATA_KEYS):
                continue
            clean[key] = scrub_metadata(item)
        return clean
    if isinstance(value, list):
        return [scrub_metadata(item) for item in value]
    return value


def record_auth_event(
    event_type,
    status,
    request,
    *,
    actor=None,
    target_user=None,
    company=None,
    workos_user_id="",
    workos_organization_id="",
    metadata=None,
):
    safe_metadata = scrub_metadata(metadata or {})
    audit_log = AuthAuditLog.objects.create(
        event_type=event_type,
        status=status,
        actor=actor,
        target_user=target_user,
        company=company,
        workos_user_id=workos_user_id or "",
        workos_organization_id=workos_organization_id or "",
        ip_address=request_ip(request),
        user_agent=request_user_agent(request)[:2000],
        metadata=safe_metadata,
    )

    if company and company.workos_organization_id and settings.WORKOS_API_KEY and settings.WORKOS_CLIENT_ID:
        try:
            emit_workos_audit_event(audit_log)
        except Exception:
            logger.warning("WorkOS Audit Log emission failed for auth audit log %s", audit_log.id, exc_info=True)
    return audit_log


def workos_audit_metadata(metadata):
    clean = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[str(key)] = value
        else:
            clean[str(key)] = json.dumps(value, default=str)[:1000]
    return clean


def emit_workos_audit_event(audit_log):
    from workos.audit_logs.models import AuditLogEvent, AuditLogEventActor, AuditLogEventContext

    client = get_workos_client()
    actor_id = audit_log.workos_user_id or (str(audit_log.actor_id) if audit_log.actor_id else "anonymous")
    target_id = audit_log.workos_user_id or (str(audit_log.target_user_id) if audit_log.target_user_id else actor_id)
    event = AuditLogEvent(
        action=audit_log.event_type,
        occurred_at=audit_log.created_at,
        version=1,
        actor=AuditLogEventActor(
            type="user" if audit_log.workos_user_id or audit_log.actor_id else "anonymous",
            id=actor_id,
        ),
        targets=[
            AuditLogEventActor(
                type="user",
                id=target_id,
            )
        ],
        context=AuditLogEventContext(
            location=str(audit_log.ip_address or ""),
            user_agent=audit_log.user_agent,
        ),
        metadata=workos_audit_metadata(audit_log.metadata),
    )
    client.audit_logs.create_event(
        organization_id=audit_log.company.workos_organization_id,
        event=event,
        idempotency_key=audit_log.id,
    )


def issue_metro_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


def extract_error_payload(exc):
    for attr in ("json_body", "body", "response"):
        value = getattr(exc, attr, None)
        if isinstance(value, dict):
            return value
        if hasattr(value, "json"):
            try:
                payload = value.json()
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass

    payload = {}
    for attr in (
        "code",
        "error",
        "message",
        "pending_authentication_token",
        "authentication_factors",
        "organizations",
        "user",
        "email",
    ):
        value = getattr(exc, attr, None)
        if value is not None:
            payload[attr] = value
    return payload


def normalize_pending_payload(payload):
    code = payload.get("code") or payload.get("error")
    pending_payload = {
        "status": "pending",
        "type": code,
        "detail": "Additional verification is required.",
    }
    if code in {"mfa_challenge", "mfa_enrollment"}:
        pending_payload["pending_authentication_token"] = payload.get("pending_authentication_token")
        pending_payload["authentication_factors"] = payload.get("authentication_factors", [])
    elif code == "organization_selection_required":
        pending_payload["pending_authentication_token"] = payload.get("pending_authentication_token")
        pending_payload["organizations"] = payload.get("organizations", [])
    elif code == "email_verification_required":
        pending_payload["pending_authentication_token"] = payload.get("pending_authentication_token")
        pending_payload["email"] = payload.get("email")
    else:
        pending_payload["detail"] = GENERIC_AUTH_ERROR
    return pending_payload


def handle_workos_exception(exc):
    payload = extract_error_payload(exc)
    logger.info("WorkOS authentication failed: %s", scrub_metadata(payload))
    code = payload.get("code") or payload.get("error")
    if code in {
        "email_verification_required",
        "mfa_challenge",
        "mfa_enrollment",
        "organization_selection_required",
    }:
        raise WorkOSPendingAuthentication(normalize_pending_payload(payload)) from exc
    raise WorkOSAuthenticationFailed(payload=payload) from exc


def authenticate_with_password(email, password, request):
    client = get_workos_client()
    try:
        return client.user_management.authenticate_with_password(
            email=email,
            password=password,
            ip_address=request_ip(request),
            user_agent=request_user_agent(request),
        )
    except Exception as exc:
        handle_workos_exception(exc)


def create_magic_auth(email):
    client = get_workos_client()
    try:
        return client.user_management.create_magic_auth(email=email)
    except Exception as exc:
        handle_workos_exception(exc)


def authenticate_with_magic_auth(email, code, request):
    client = get_workos_client()
    try:
        return client.user_management.authenticate_with_magic_auth(
            email=email,
            code=code,
            ip_address=request_ip(request),
            user_agent=request_user_agent(request),
        )
    except Exception as exc:
        handle_workos_exception(exc)


def authenticate_with_code(code, request):
    client = get_workos_client()
    try:
        return client.user_management.authenticate_with_code(
            code=code,
            ip_address=request_ip(request),
            user_agent=request_user_agent(request),
        )
    except Exception as exc:
        handle_workos_exception(exc)


def challenge_mfa_factor(authentication_factor_id):
    client = get_workos_client()
    try:
        return client.mfa.challenge_factor(authentication_factor_id=authentication_factor_id)
    except Exception as exc:
        handle_workos_exception(exc)


def authenticate_with_totp(pending_authentication_token, authentication_challenge_id, code, request):
    client = get_workos_client()
    try:
        return client.user_management.authenticate_with_totp(
            pending_authentication_token=pending_authentication_token,
            authentication_challenge_id=authentication_challenge_id,
            code=code,
            ip_address=request_ip(request),
            user_agent=request_user_agent(request),
        )
    except Exception as exc:
        handle_workos_exception(exc)


def authenticate_with_organization_selection(pending_authentication_token, organization_id, request):
    client = get_workos_client()
    try:
        return client.user_management.authenticate_with_organization_selection(
            pending_authentication_token=pending_authentication_token,
            organization_id=organization_id,
            ip_address=request_ip(request),
            user_agent=request_user_agent(request),
        )
    except Exception as exc:
        handle_workos_exception(exc)


def get_workos_user(workos_user_id):
    client = get_workos_client()
    return client.user_management.get_user(workos_user_id)


def list_workos_memberships(workos_user_id, workos_organization_id=None):
    client = get_workos_client()
    kwargs = {"user_id": workos_user_id, "limit": 100}
    if workos_organization_id:
        kwargs["organization_id"] = workos_organization_id
    page = client.user_management.list_organization_memberships(**kwargs)
    return list(getattr(page, "data", []) or as_plain_data(page).get("data", []))


def get_workos_authorization_url(state):
    client = get_workos_client()
    return client.user_management.get_authorization_url(
        redirect_uri=settings.WORKOS_REDIRECT_URI,
        provider="GoogleOAuth",
        state=state,
    )


def normalize_redirect_path(value):
    value = (value or "").strip()
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/dockets/new"
    if value == "/" or value.startswith("/sign-in"):
        return "/dockets/new"
    return value


def create_google_state(redirect_url):
    nonce = secrets.token_urlsafe(24)
    cache_key = f"{GOOGLE_STATE_CACHE_PREFIX}{nonce}"
    cache.set(cache_key, True, timeout=settings.WORKOS_GOOGLE_STATE_TTL_SECONDS)
    return signing.dumps(
        {"nonce": nonce, "redirect_url": normalize_redirect_path(redirect_url)},
        salt=GOOGLE_STATE_SALT,
    )


def consume_google_state(state):
    try:
        payload = signing.loads(
            state,
            salt=GOOGLE_STATE_SALT,
            max_age=settings.WORKOS_GOOGLE_STATE_TTL_SECONDS,
        )
    except signing.BadSignature as exc:
        raise WorkOSAuthenticationFailed("Invalid sign-in state.") from exc

    nonce = payload.get("nonce")
    cache_key = f"{GOOGLE_STATE_CACHE_PREFIX}{nonce}"
    if not nonce or not cache.get(cache_key):
        raise WorkOSAuthenticationFailed("Invalid sign-in state.")
    cache.delete(cache_key)
    return normalize_redirect_path(payload.get("redirect_url"))


def create_google_exchange_code(user, redirect_url):
    code = secrets.token_urlsafe(32)
    cache.set(
        f"{GOOGLE_EXCHANGE_CACHE_PREFIX}{code}",
        {"user_id": user.id, "redirect_url": normalize_redirect_path(redirect_url)},
        timeout=settings.WORKOS_GOOGLE_EXCHANGE_TTL_SECONDS,
    )
    return code


def create_google_pending_exchange_code(pending_payload, redirect_url):
    code = secrets.token_urlsafe(32)
    cache.set(
        f"{GOOGLE_EXCHANGE_CACHE_PREFIX}{code}",
        {"pending": pending_payload, "redirect_url": normalize_redirect_path(redirect_url)},
        timeout=settings.WORKOS_GOOGLE_EXCHANGE_TTL_SECONDS,
    )
    return code


def consume_google_exchange_code(exchange_code):
    cache_key = f"{GOOGLE_EXCHANGE_CACHE_PREFIX}{exchange_code}"
    payload = cache.get(cache_key)
    if not payload:
        raise WorkOSAuthenticationFailed("Invalid or expired sign-in code.")
    cache.delete(cache_key)
    return payload


def frontend_callback_url(params):
    query = urlencode(params)
    separator = "&" if "?" in settings.WORKOS_FRONTEND_CALLBACK_URL else "?"
    return f"{settings.WORKOS_FRONTEND_CALLBACK_URL}{separator}{query}"


def _workos_user_id(workos_user):
    return workos_user.get("id") or workos_user.get("user_id")


def _workos_user_email(workos_user):
    return (workos_user.get("email") or "").strip().lower()


def _unique_username_from_email(email):
    base = (email.split("@", 1)[0] or "user").replace(" ", "_")[:140]
    username = base
    suffix = 1
    while User.objects.filter(username__iexact=username).exists():
        suffix += 1
        username = f"{base[:135]}_{suffix}"
    return username


def _split_full_name(full_name):
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _first_page_item(page):
    data = list(getattr(page, "data", []) or as_plain_data(page).get("data", []))
    return data[0] if data else None


def _workos_role_slug_for_metro_role(role):
    seed_role_templates()
    definition = RoleDefinition.objects.filter(code=role, is_active=True).first()
    if definition and definition.workos_role_slug:
        return definition.workos_role_slug
    for slug, mapped_role in settings.WORKOS_ROLE_MAPPING.items():
        if mapped_role == role:
            return slug
    return str(role).lower().replace("_", "-")


def _find_or_create_workos_organization(company):
    client = get_workos_client()
    if company.workos_organization_id:
        return client.organizations.get_organization(company.workos_organization_id)

    existing = _first_page_item(client.organizations.list_organizations(search=company.name, limit=10))
    existing_data = as_plain_data(existing)
    if existing_data.get("id") and (existing_data.get("name") or "").strip().lower() == company.name.strip().lower():
        company.workos_organization_id = existing_data["id"]
        company.save(update_fields=["workos_organization_id"])
        return existing

    organization = client.organizations.create_organization(
        name=company.name,
        metadata={"metro_company_id": str(company.id)},
    )
    organization_data = as_plain_data(organization)
    company.workos_organization_id = organization_data.get("id", "")
    company.save(update_fields=["workos_organization_id"])
    return organization


def _find_or_create_workos_user(signup_request, password):
    client = get_workos_client()
    email = signup_request.email.strip().lower()
    existing = _first_page_item(client.user_management.list_users(email=email, limit=1))
    if existing:
        first_name, last_name = _split_full_name(signup_request.full_name)
        return client.user_management.update_user(
            as_plain_data(existing)["id"],
            first_name=first_name,
            last_name=last_name,
            name=signup_request.full_name,
            metadata={
                "metro_signup_request_id": str(signup_request.id),
                "metro_company_name": signup_request.company_name,
            },
        )

    first_name, last_name = _split_full_name(signup_request.full_name)
    kwargs = {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "name": signup_request.full_name,
        "email_verified": False,
        "metadata": {
            "metro_signup_request_id": str(signup_request.id),
            "metro_company_name": signup_request.company_name,
        },
    }
    if password:
        kwargs["password"] = _workos_password(password)
    return client.user_management.create_user(**kwargs)


def _find_or_create_local_signup_company(company_name):
    company = Company.objects.filter(name__iexact=company_name.strip()).first()
    if company:
        return company, False
    return Company.objects.create(name=company_name.strip(), is_active=False), True


def _ensure_local_signup_user(signup_request, workos_user):
    workos_data = as_plain_data(workos_user)
    email = (workos_data.get("email") or signup_request.email).strip().lower()
    first_name, last_name = _split_full_name(signup_request.full_name)
    user = None
    workos_user_id = workos_data.get("id") or workos_data.get("user_id")
    if workos_user_id:
        user = User.objects.filter(workos_user_id=workos_user_id).first()
    if not user:
        user = User.objects.filter(email__iexact=email).first()
    if not user:
        user = User(
            username=_unique_username_from_email(email),
            email=email,
        )
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    user.company = signup_request.company
    user.workos_user_id = workos_user_id
    user.is_active = False
    user.set_unusable_password()
    user.save()
    return user


def notify_owner_of_signup(signup_request, request=None):
    owner_email = getattr(settings, "METRO_OWNER_EMAIL", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "")
    if not owner_email:
        return
    review_url = getattr(settings, "METRO_SIGNUP_REVIEW_URL", "")
    body = "\n".join(
        [
            "A new Metro signup is waiting for approval.",
            "",
            f"Name: {signup_request.full_name}",
            f"Email: {signup_request.email}",
            f"Company: {signup_request.company_name}",
            f"Phone: {signup_request.phone or '-'}",
            "",
            "Message:",
            signup_request.message or "-",
            "",
            f"Signup request ID: {signup_request.id}",
            f"Review URL: {review_url}" if review_url else "",
        ]
    ).strip()
    send_mail(
        subject=f"Metro signup approval needed - {signup_request.company_name}",
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[owner_email],
        fail_silently=True,
    )


@transaction.atomic
def create_pending_signup(signup_request, password):
    company, _ = _find_or_create_local_signup_company(signup_request.company_name)
    signup_request.company = company
    organization = _find_or_create_workos_organization(company)
    workos_user = _find_or_create_workos_user(signup_request, password)
    signup_request.workos_user_id = as_plain_data(workos_user).get("id") or as_plain_data(workos_user).get("user_id") or ""
    signup_request.workos_organization_id = as_plain_data(organization).get("id") or ""
    signup_request.user = _ensure_local_signup_user(signup_request, workos_user)
    signup_request.save(
        update_fields=[
            "company",
            "user",
            "workos_user_id",
            "workos_organization_id",
            "updated_at",
        ]
    )
    return signup_request


@transaction.atomic
def approve_pending_signup(signup_request, approver, *, role, office=None):
    if signup_request.status != SignupRequest.Status.PENDING:
        raise MetroAccessDenied("Signup request is not pending.")
    if role_requires_office(role) and not office:
        raise MetroAccessDenied("Office is required for this role.")
    if not role_requires_office(role):
        office = None

    company = signup_request.company
    if not company:
        company, _ = _find_or_create_local_signup_company(signup_request.company_name)
        signup_request.company = company

    organization = _find_or_create_workos_organization(company)
    organization_id = as_plain_data(organization).get("id") or company.workos_organization_id
    if not signup_request.workos_user_id:
        workos_user = _find_or_create_workos_user(signup_request, None)
        signup_request.workos_user_id = as_plain_data(workos_user).get("id") or as_plain_data(workos_user).get("user_id") or ""

    role_slug = _workos_role_slug_for_metro_role(role)
    membership = get_workos_client().organization_membership.create_organization_membership(
        user_id=signup_request.workos_user_id,
        organization_id=organization_id,
        role=_workos_single_role(role_slug),
    )
    membership_id = as_plain_data(membership).get("id", "")

    company.is_active = True
    company.workos_organization_id = organization_id
    company.save(update_fields=["is_active", "workos_organization_id"])

    user = signup_request.user
    if not user:
        workos_user = get_workos_client().user_management.get_user(signup_request.workos_user_id)
        user = _ensure_local_signup_user(signup_request, workos_user)
    user.company = company
    user.office = office
    user.is_active = True
    user.save(update_fields=["company", "office", "is_active"])

    UserMembership.unscoped_objects.update_or_create(
        user=user,
        company=company,
        office=office,
        role=role,
        defaults={
            "is_active": True,
            "workos_organization_membership_id": membership_id,
            "workos_role_slug": role_slug,
        },
    )

    signup_request.user = user
    signup_request.company = company
    signup_request.workos_organization_id = organization_id
    signup_request.workos_organization_membership_id = membership_id
    signup_request.mark_approved(approver)
    signup_request.save()
    return signup_request


def _role_slugs_from_membership(membership):
    data = as_plain_data(membership)
    slugs = []
    if data.get("role_slug"):
        slugs.append(data["role_slug"])
    if data.get("role_slugs"):
        slugs.extend(data["role_slugs"])
    role = data.get("role")
    if isinstance(role, dict) and role.get("slug"):
        slugs.append(role["slug"])
    roles = data.get("roles") or []
    for role_data in roles:
        if isinstance(role_data, dict) and role_data.get("slug"):
            slugs.append(role_data["slug"])
        elif isinstance(role_data, str):
            slugs.append(role_data)
    return [slug for slug in slugs if slug]


def _membership_id(membership):
    return as_plain_data(membership).get("id", "")


def _membership_is_active(membership):
    status = (as_plain_data(membership).get("status") or "active").lower()
    return status == "active"


def map_workos_role_to_metro_role(workos_role_slug):
    seed_role_templates()
    if not workos_role_slug:
        return Role.VIEWER
    definition = RoleDefinition.objects.filter(workos_role_slug__iexact=workos_role_slug, is_active=True).first()
    if definition:
        return definition.code
    role_code = settings.WORKOS_ROLE_MAPPING.get(workos_role_slug)
    if not role_code:
        role_code = settings.WORKOS_ROLE_MAPPING.get(workos_role_slug.lower().replace("_", "-"))
    if role_code and RoleDefinition.objects.filter(code=role_code, is_active=True).exists():
        return role_code
    raise MetroAccessDenied("WorkOS role is not mapped to a Metro role.")


def _company_from_workos_organization(workos_organization_id):
    if not workos_organization_id:
        return None
    return Company.objects.filter(workos_organization_id=workos_organization_id, is_active=True).first()


def _single_local_company(user):
    memberships = list(
        UserMembership.unscoped_objects.filter(user=user, is_active=True).select_related("company")
    )
    company_ids = {membership.company_id for membership in memberships if membership.company and membership.company.is_active}
    if len(company_ids) != 1:
        return None
    return memberships[0].company


def _sync_profile(user, workos_user):
    email = _workos_user_email(workos_user)
    update_fields = ["workos_user_id", "email", "first_name", "last_name", "password"]
    user.workos_user_id = _workos_user_id(workos_user)
    if email:
        user.email = email
    user.first_name = workos_user.get("first_name") or user.first_name
    user.last_name = workos_user.get("last_name") or user.last_name
    user.set_unusable_password()
    user.save(update_fields=update_fields)


def _resolve_or_provision_user(workos_user, company):
    workos_user_id = _workos_user_id(workos_user)
    email = _workos_user_email(workos_user)
    user = User.objects.filter(workos_user_id=workos_user_id).first()
    if not user and email:
        user = User.objects.filter(email__iexact=email).first()

    if not user:
        if not settings.WORKOS_AUTO_PROVISION_USERS or not company:
            raise MetroAccessDenied("WorkOS user is not provisioned in Metro.")
        user = User(
            username=_unique_username_from_email(email),
            email=email,
            first_name=workos_user.get("first_name") or "",
            last_name=workos_user.get("last_name") or "",
            company=company,
        )
        user.set_unusable_password()
        user.save()

    if not user.is_active:
        raise MetroAccessDenied("User is inactive.")

    _sync_profile(user, workos_user)
    if company and not user.company_id:
        user.company = company
        user.save(update_fields=["company"])
    return user


def _active_membership_for_org(workos_user_id, workos_organization_id):
    memberships = list_workos_memberships(workos_user_id, workos_organization_id)
    for membership in memberships:
        if _membership_is_active(membership):
            return membership
    return None


def _sync_membership_from_workos(user, company, workos_membership):
    slugs = _role_slugs_from_membership(workos_membership)
    role_slug = slugs[0] if slugs else ""
    metro_role = map_workos_role_to_metro_role(role_slug)
    membership_id = _membership_id(workos_membership)

    existing = list(
        UserMembership.unscoped_objects.filter(user=user, company=company, is_active=True).select_related("office")
    )
    if role_requires_office(metro_role):
        office_memberships = [membership for membership in existing if membership.office_id]
        if not office_memberships:
            raise MetroAccessDenied("Metro branch access is required.")
        for membership in office_memberships:
            membership.role = metro_role
            membership.workos_role_slug = role_slug
            membership.workos_organization_membership_id = membership_id
            membership.save(update_fields=["role", "workos_role_slug", "workos_organization_membership_id", "updated_at"])
        return

    UserMembership.unscoped_objects.filter(user=user, company=company, is_active=True).exclude(
        Q(office__isnull=True) & Q(role=metro_role)
    ).update(is_active=False)
    UserMembership.unscoped_objects.update_or_create(
        user=user,
        company=company,
        office=None,
        role=metro_role,
        defaults={
            "is_active": True,
            "workos_role_slug": role_slug,
            "workos_organization_membership_id": membership_id,
        },
    )


def _ensure_local_access(user, company):
    if not company:
        memberships = UserMembership.unscoped_objects.filter(user=user, is_active=True)
    else:
        memberships = UserMembership.unscoped_objects.filter(user=user, company=company, is_active=True)
    if not memberships.exists():
        raise MetroAccessDenied("Metro access is not configured.")
    for membership in memberships:
        if role_requires_office(membership.role) and not membership.office_id:
            raise MetroAccessDenied("Metro branch access is required.")


@transaction.atomic
def sync_workos_authentication(auth_response):
    auth_data = as_plain_data(auth_response)
    workos_user = as_plain_data(auth_data.get("user"))
    workos_user_id = _workos_user_id(workos_user)
    workos_organization_id = auth_data.get("organization_id") or auth_data.get("organizationId")
    if not workos_user_id:
        raise MetroAccessDenied("WorkOS user was missing from authentication response.")

    company = _company_from_workos_organization(workos_organization_id)
    existing_user = User.objects.filter(workos_user_id=workos_user_id).first()
    if not company and existing_user:
        company = _single_local_company(existing_user)
    if workos_organization_id and not company:
        raise MetroAccessDenied("WorkOS organization is not linked to a Metro company.")

    user = _resolve_or_provision_user(workos_user, company)
    if not company:
        company = _single_local_company(user)

    if company and company.workos_organization_id:
        workos_membership = _active_membership_for_org(workos_user_id, company.workos_organization_id)
        if not workos_membership:
            UserMembership.unscoped_objects.filter(user=user, company=company).update(is_active=False)
            raise MetroAccessDenied("WorkOS organization membership is inactive.")
        _sync_membership_from_workos(user, company, workos_membership)

    _ensure_local_access(user, company)
    user.refresh_from_db()
    return user, company


def sync_current_user_from_workos(user, company=None):
    if not user.workos_user_id:
        _ensure_local_access(user, company)
        return user

    workos_user = as_plain_data(get_workos_user(user.workos_user_id))
    workos_organization_id = company.workos_organization_id if company else None
    if company and workos_organization_id:
        membership = _active_membership_for_org(user.workos_user_id, workos_organization_id)
        if not membership:
            UserMembership.unscoped_objects.filter(user=user, company=company).update(is_active=False)
            raise MetroAccessDenied("WorkOS organization membership is inactive.")
        _sync_membership_from_workos(user, company, membership)
    _sync_profile(user, workos_user)
    _ensure_local_access(user, company)
    user.refresh_from_db()
    return user
