from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.contrib.postgres.indexes import GinIndex
from ulid import ULID
from core.request_context import get_current_user, get_current_company


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
    """
    Automatically filters querysets by the current company context and user roles.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        user = get_current_user()
        
        if not user or not user.is_authenticated:
            return qs

        from core.policies import has_role
        from core.models import Role

        # Platform admins see everything
        if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
            return qs

        company = get_current_company()
        if company and hasattr(self.model, 'company'):
            qs = qs.filter(company=company)
        
        # Enforce branch scoping for non-Client Super Admins
        if company and not has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN]):
            from core.models import UserMembership
            active_branches = UserMembership.unscoped_objects.filter(
                user=user, 
                company=company, 
                is_active=True
            ).values_list('branch', flat=True)
            
            # For models with a direct 'branch' reference
            if hasattr(self.model, 'branch'):
                qs = qs.filter(models.Q(branch__in=active_branches) | models.Q(branch__isnull=True))
                
            # For Dockets which use origin_branch and destination_branch
            elif hasattr(self.model, 'origin_branch') and hasattr(self.model, 'destination_branch'):
                qs = qs.filter(
                    models.Q(origin_branch__in=active_branches) | 
                    models.Q(destination_branch__in=active_branches)
                )

        return qs

class AuditBaseModel(models.Model):
    id = models.CharField(max_length=26, primary_key=True, default=generate_ulid, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='%(app_label)s_%(class)s_updated',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    is_active = models.BooleanField(default=True)

    # Managers
    objects = TenantManager()
    unscoped_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        user_context = get_current_user()
        company_context = get_current_company()
        
        authenticated_user = user_context if user_context and user_context.is_authenticated else None
        
        if authenticated_user:
            if not self.pk and not self.created_by:
                self.created_by = authenticated_user
            self.updated_by = authenticated_user
            
            # Automatically assign company if model has a company field
            if hasattr(self, 'company') and not self.company_id:
                # Try context first, then fallback to user's own company
                company = company_context or getattr(authenticated_user, 'company', None)
                if company:
                    self.company = company

        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            update_fields = set(update_fields)
            update_fields.add('updated_at')
            if authenticated_user:
                update_fields.add('updated_by')
                if not self.pk:
                    update_fields.add('created_by')
            kwargs['update_fields'] = list(update_fields)

        super().save(*args, **kwargs)

class State(AuditBaseModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=5, unique=True, help_text=_("Standard state code (e.g., MH, KA)"))

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.code})"

class City(AuditBaseModel):
    name = models.CharField(max_length=100)
    state = models.ForeignKey(State, related_name='cities', on_delete=models.CASCADE)

    class Meta:
        verbose_name_plural = "Cities"
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['name', 'state'], name='unique_city_per_state')
        ]

    def __str__(self):
        return f"{self.name}, {self.state.code}"

class Branch(AuditBaseModel):
    company = models.ForeignKey(Company, related_name='branches', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    city = models.ForeignKey(City, related_name='branches', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name_plural = "Branches"
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_branch_per_company')
        ]
        indexes = [
            GinIndex(
                name='branch_name_trgm_idx', 
                fields=['name'], 
                opclasses=['gin_trgm_ops']
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.company.name})"

class User(AbstractUser):
    company = models.ForeignKey(Company, related_name='users', on_delete=models.CASCADE, null=True, blank=True)
    branch = models.ForeignKey(Branch, related_name='users', on_delete=models.SET_NULL, null=True, blank=True)
    is_owner = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower('username'),
                name='unique_lower_username'
            )
        ]

class Role(models.TextChoices):
    PLATFORM_ADMIN = 'PLATFORM_ADMIN', _('Platform Admin')
    CLIENT_SUPER_ADMIN = 'CLIENT_SUPER_ADMIN', _('Client Super Admin')
    BRANCH_ADMIN = 'BRANCH_ADMIN', _('Branch Admin')
    BOOKING_USER = 'BOOKING_USER', _('Booking User')
    DELIVERY_USER = 'DELIVERY_USER', _('Delivery User')
    ACCOUNTANT = 'ACCOUNTANT', _('Accountant')
    VIEWER = 'VIEWER', _('Viewer')

class UserMembership(AuditBaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='memberships', on_delete=models.CASCADE)
    company = models.ForeignKey(Company, related_name='memberships', on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, related_name='memberships', on_delete=models.CASCADE, null=True, blank=True)
    role = models.CharField(max_length=50, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'company', 'branch', 'role'],
                name='unique_user_membership'
            ),
            models.CheckConstraint(
                condition=~models.Q(role__in=[Role.BRANCH_ADMIN, Role.BOOKING_USER, Role.DELIVERY_USER]) | models.Q(branch__isnull=False),
                name='active_branch_required_for_operational_roles'
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.company.name} - {self.role}"

class Party(AuditBaseModel):
    company = models.ForeignKey(Company, related_name='parties', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    phone = models.CharField(
        max_length=10, 
        validators=[RegexValidator(r'^\d{10}$', _('Phone number must be exactly 10 digits.'))]
    )
    address = models.TextField()
    city = models.ForeignKey(City, related_name='parties', on_delete=models.PROTECT)
    gst_number = models.CharField(
        max_length=15, 
        blank=True, 
        null=True,
        validators=[
            RegexValidator(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$', _('Invalid Indian GSTIN format.'))
        ]
    )

    class Meta:
        verbose_name_plural = "Parties"
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower('name'),
                'phone',
                'company',
                name='unique_party_per_company'
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.city.name})"
