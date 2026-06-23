from django.contrib import admin

from authentication.models import AuthAuditLog


@admin.register(AuthAuditLog)
class AuthAuditLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "status", "actor", "target_user", "company", "created_at")
    list_filter = ("event_type", "status", "created_at")
    search_fields = ("workos_user_id", "workos_organization_id", "actor__username", "target_user__username")
    readonly_fields = (
        "id",
        "event_type",
        "status",
        "actor",
        "target_user",
        "company",
        "workos_user_id",
        "workos_organization_id",
        "ip_address",
        "user_agent",
        "metadata",
        "created_at",
    )
