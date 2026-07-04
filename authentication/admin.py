from django.contrib import admin

from authentication.models import AuthAuditLog, SignupRequest


@admin.register(SignupRequest)
class SignupRequestAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "company_name", "status", "created_at", "approved_at")
    list_filter = ("status", "created_at", "approved_at")
    search_fields = ("email", "full_name", "company_name", "workos_user_id", "workos_organization_id")
    readonly_fields = (
        "id",
        "workos_user_id",
        "workos_organization_id",
        "workos_organization_membership_id",
        "approved_by",
        "approved_at",
        "rejected_by",
        "rejected_at",
        "created_at",
        "updated_at",
    )


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
