from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from ulid import ULID

from core.request_context import get_current_company, get_current_user


def generate_ulid():
    return str(ULID())


class Company(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name


class TenantManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        user = get_current_user()
        if not user or not user.is_authenticated:
            return qs

        from core.policies import active_office_ids, has_role

        if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
            return qs

        company = get_current_company()
        if company and hasattr(self.model, "company"):
            qs = qs.filter(company=company)

        if company and not has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN]):
            office_ids = active_office_ids(user, company)
            if hasattr(self.model, "office"):
                qs = qs.filter(models.Q(office__in=office_ids) | models.Q(office__isnull=True))
            elif hasattr(self.model, "origin_office") and hasattr(self.model, "destination_office"):
                qs = qs.filter(
                    models.Q(origin_office__in=office_ids)
                    | models.Q(destination_office__in=office_ids)
                    | models.Q(events__office__in=office_ids)
                ).distinct()

        return qs


class AuditBaseModel(models.Model):
    id = models.CharField(max_length=26, primary_key=True, default=generate_ulid, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_created",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="%(app_label)s_%(class)s_updated",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    objects = TenantManager()
    unscoped_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        user = get_current_user()
        company = get_current_company()
        authenticated_user = user if user and user.is_authenticated else None

        if authenticated_user:
            if not self.pk and not self.created_by:
                self.created_by = authenticated_user
            self.updated_by = authenticated_user
            if hasattr(self, "company") and not self.company_id:
                fallback_company = company or getattr(authenticated_user, "company", None)
                if fallback_company:
                    self.company = fallback_company

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            update_fields.add("updated_at")
            if authenticated_user:
                update_fields.add("updated_by")
                if not self.pk:
                    update_fields.add("created_by")
            kwargs["update_fields"] = list(update_fields)

        super().save(*args, **kwargs)


class State(AuditBaseModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=5, unique=True, help_text=_("Standard state code (e.g., MH, KA)"))

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class City(AuditBaseModel):
    name = models.CharField(max_length=100)
    state = models.ForeignKey(State, related_name="cities", on_delete=models.CASCADE)

    class Meta:
        verbose_name_plural = "Cities"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["name", "state"], name="unique_city_per_state"),
        ]

    def __str__(self):
        return f"{self.name}, {self.state.code}"


class OfficeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    INACTIVE = "INACTIVE", _("Inactive")
    ARCHIVED = "ARCHIVED", _("Archived")


class GlobalOffice(AuditBaseModel):
    name = models.CharField(max_length=255)
    city = models.ForeignKey(City, related_name="global_offices", on_delete=models.PROTECT)
    owner_company = models.ForeignKey(
        Company,
        related_name="owned_global_offices",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    address = models.TextField(blank=True, null=True)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^\d{10}$", _("Phone number must be exactly 10 digits."))],
    )
    status = models.CharField(max_length=20, choices=OfficeStatus.choices, default=OfficeStatus.ACTIVE)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"),
                "city",
                name="unique_global_office_name_city",
            )
        ]
        indexes = [
            GinIndex(name="global_office_name_trgm_idx", fields=["name"], opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.city})"


class CompanyOffice(AuditBaseModel):
    class OfficeType(models.TextChoices):
        OWN = "OWN", _("Own Office")
        PARTNER = "PARTNER", _("Partner Office")
        MANUAL = "MANUAL", _("Manual Office")

    company = models.ForeignKey(Company, related_name="offices", on_delete=models.CASCADE)
    global_office = models.ForeignKey(
        GlobalOffice,
        related_name="company_copies",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Discovery/import source only. Runtime operations never reference GlobalOffice."),
    )
    name = models.CharField(max_length=255)
    city = models.ForeignKey(City, related_name="company_offices", on_delete=models.PROTECT)
    office_type = models.CharField(max_length=20, choices=OfficeType.choices, default=OfficeType.OWN)
    address = models.TextField(blank=True, null=True)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^\d{10}$", _("Phone number must be exactly 10 digits."))],
    )
    status = models.CharField(max_length=20, choices=OfficeStatus.choices, default=OfficeStatus.ACTIVE)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Company Office"
        verbose_name_plural = "Company Offices"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_office_per_company"),
        ]
        indexes = [
            GinIndex(name="company_office_name_trgm_idx", fields=["name"], opclasses=["gin_trgm_ops"]),
        ]

    @classmethod
    def copy_from_global(cls, company, global_office, office_type=None):
        return cls(
            company=company,
            global_office=global_office,
            name=global_office.name,
            city=global_office.city,
            office_type=office_type or cls.OfficeType.PARTNER,
            address=global_office.address,
            contact_name=global_office.contact_name,
            phone=global_office.phone,
            status=global_office.status,
        )

    def refresh_from_global(self, fields=None):
        if not self.global_office_id:
            return
        fields = fields or ["name", "city", "address", "contact_name", "phone", "status"]
        for field in fields:
            setattr(self, field, getattr(self.global_office, field))
        self.save(update_fields=[*fields, "updated_at"])

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class User(AbstractUser):
    company = models.ForeignKey(Company, related_name="users", on_delete=models.CASCADE, null=True, blank=True)
    office = models.ForeignKey(CompanyOffice, related_name="users", on_delete=models.SET_NULL, null=True, blank=True)
    is_owner = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(models.functions.Lower("username"), name="unique_lower_username"),
        ]


class Role(models.TextChoices):
    PLATFORM_ADMIN = "PLATFORM_ADMIN", _("Platform Admin")
    CLIENT_SUPER_ADMIN = "CLIENT_SUPER_ADMIN", _("Client Super Admin")
    OFFICE_ADMIN = "OFFICE_ADMIN", _("Office Admin")
    BOOKING_USER = "BOOKING_USER", _("Booking User")
    DELIVERY_USER = "DELIVERY_USER", _("Delivery User")
    ACCOUNTANT = "ACCOUNTANT", _("Accountant")
    VIEWER = "VIEWER", _("Viewer")


class UserMembership(AuditBaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="memberships", on_delete=models.CASCADE)
    company = models.ForeignKey(Company, related_name="memberships", on_delete=models.CASCADE)
    office = models.ForeignKey(CompanyOffice, related_name="memberships", on_delete=models.CASCADE, null=True, blank=True)
    role = models.CharField(max_length=50, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "company", "office", "role"], name="unique_user_membership"),
            models.CheckConstraint(
                condition=~models.Q(role__in=[Role.OFFICE_ADMIN, Role.BOOKING_USER, Role.DELIVERY_USER])
                | models.Q(office__isnull=False),
                name="office_required_for_operational_roles",
            ),
        ]

    def __str__(self):
        office = self.office.name if self.office else "Company"
        return f"{self.user.username} - {self.company.name} - {office} - {self.role}"


class Party(AuditBaseModel):
    company = models.ForeignKey(Company, related_name="parties", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    phone = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^\d{10}$", _("Phone number must be exactly 10 digits."))],
    )
    address = models.TextField(blank=True, null=True)
    city = models.ForeignKey(City, related_name="parties", on_delete=models.PROTECT)
    gst_number = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$",
                _("Invalid Indian GSTIN format."),
            )
        ],
    )

    class Meta:
        verbose_name_plural = "Parties"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"),
                "phone",
                "company",
                name="unique_party_per_company",
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.city.name})"
