from django.contrib import admin

from core.models import RoleDefinition


@admin.register(RoleDefinition)
class RoleDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "requires_office", "is_active", "sort_order")
    list_filter = ("requires_office", "is_active")
    search_fields = ("code", "name")
    ordering = ("sort_order", "name")
