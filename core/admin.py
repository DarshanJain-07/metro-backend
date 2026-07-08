from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from core.import_export_admin import RequestContextResourceAdminMixin
from core.import_export_resources import CityResource, CompanyOfficeResource, PartyResource, StateResource
from core.models import City, CompanyOffice, Party, RoleDefinition, State


@admin.register(State)
class StateAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [StateResource]
    list_display = ("name", "code", "is_active")
    search_fields = ("name", "code")


@admin.register(City)
class CityAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [CityResource]
    list_display = ("name", "state", "is_active")
    list_filter = ("state", "is_active")
    search_fields = ("name", "state__name", "state__code")


@admin.register(CompanyOffice)
class CompanyOfficeAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [CompanyOfficeResource]
    list_display = ("name", "company", "city", "status", "is_active")
    list_filter = ("status", "is_active", "company")
    search_fields = ("name", "company__name", "city__name", "phone", "gst_number")


@admin.register(Party)
class PartyAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [PartyResource]
    list_display = ("name", "company", "phone", "city", "is_active")
    list_filter = ("is_active", "company", "city")
    search_fields = ("name", "phone", "gst_number", "city__name")


@admin.register(RoleDefinition)
class RoleDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "workos_role_slug", "name", "requires_office", "is_active", "sort_order")
    list_filter = ("requires_office", "is_active")
    search_fields = ("code", "workos_role_slug", "name")
    ordering = ("sort_order", "name")
