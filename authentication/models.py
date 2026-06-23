from django.conf import settings
from django.db import models

from core.models import Company, generate_ulid


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
