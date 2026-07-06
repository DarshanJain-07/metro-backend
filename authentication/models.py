from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Company, generate_ulid


class SignupRequest(models.Model):
    class Status(models.TextChoices):
        EMAIL_VERIFICATION_PENDING = "EMAIL_VERIFICATION_PENDING", "Email verification pending"
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    id = models.CharField(max_length=26, primary_key=True, default=generate_ulid, editable=False)
    full_name = models.CharField(max_length=255)
    username = models.CharField(max_length=150, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    company_name = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    company = models.ForeignKey(
        Company,
        related_name="signup_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="signup_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    workos_user_id = models.CharField(max_length=100, blank=True)
    workos_organization_id = models.CharField(max_length=100, blank=True)
    workos_organization_membership_id = models.CharField(max_length=100, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="approved_signup_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="rejected_signup_requests",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="authenticat_status_7e05b5_idx"),
            models.Index(fields=["email"], name="authenticat_email_b83d59_idx"),
            models.Index(fields=["workos_user_id"], name="authenticat_workos__00f709_idx"),
        ]

    def mark_approved(self, user):
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.rejected_by = None
        self.rejected_at = None
        self.rejection_reason = ""

    def mark_rejected(self, user, reason=""):
        self.status = self.Status.REJECTED
        self.rejected_by = user
        self.rejected_at = timezone.now()
        self.rejection_reason = reason

    def __str__(self):
        return f"{self.email} - {self.company_name} ({self.status})"


class UsernameEmailLookup(models.Model):
    username = models.CharField(max_length=150, primary_key=True)
    email = models.EmailField()

    class Meta:
        ordering = ["username"]
        constraints = [
            models.UniqueConstraint(models.functions.Lower("username"), name="unique_lower_auth_username_lookup"),
        ]
        indexes = [
            models.Index(models.functions.Lower("email"), name="auth_userlookup_email_idx"),
        ]

    def save(self, *args, **kwargs):
        self.username = normalize_lookup_username(self.username)
        self.email = normalize_lookup_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} -> {self.email}"


def normalize_lookup_username(username):
    return (username or "").strip().lower()


def normalize_lookup_email(email):
    return (email or "").strip().lower()


class AuthAuditLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILURE = "FAILURE", "Failure"
        PENDING = "PENDING", "Pending"

    id = models.CharField(max_length=26, primary_key=True, default=generate_ulid, editable=False)
    event_type = models.CharField(max_length=80)
    status = models.CharField(max_length=20, choices=Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="auth_audit_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="targeted_auth_audit_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        Company,
        related_name="auth_audit_events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    workos_user_id = models.CharField(max_length=100, blank=True)
    workos_organization_id = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "status", "created_at"]),
            models.Index(fields=["workos_user_id"]),
            models.Index(fields=["workos_organization_id"]),
        ]

    def __str__(self):
        return f"{self.event_type} {self.status} {self.created_at:%Y-%m-%d %H:%M:%S}"
