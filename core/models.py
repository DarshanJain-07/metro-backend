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
    Automatically filters querysets by the current company context.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        company = get_current_company()
        
        # Only filter if a company is set in the middleware context
        # and the model actually has a company field.
        if company and hasattr(self.model, 'company'):
            return qs.filter(company=company)
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
        unique_together = ('company', 'name', 'phone')
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.city.name})"
