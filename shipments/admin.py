from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from core.import_export_admin import RequestContextResourceAdminMixin
from shipments.import_export_resources import OfficeRatePolicyResource, RateCardResource, RateRuleResource
from shipments.models import OfficeRatePolicy, RateCard, RateRule


@admin.register(RateCard)
class RateCardAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [RateCardResource]
    list_display = ("name", "company", "is_default", "effective_from", "effective_to", "is_active")
    list_filter = ("company", "is_default", "is_active")
    search_fields = ("name", "company__name")


@admin.register(RateRule)
class RateRuleAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [RateRuleResource]
    list_display = ("rate_card", "origin_city", "destination_city", "basis", "rate_type", "rate", "is_active")
    list_filter = ("company", "basis", "rate_type", "is_active")
    search_fields = ("rate_card__name", "origin_city__name", "destination_city__name")


@admin.register(OfficeRatePolicy)
class OfficeRatePolicyAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [OfficeRatePolicyResource]
    list_display = ("office", "company", "can_override_rate", "max_discount_percent", "requires_approval")
    list_filter = ("company", "can_override_rate", "requires_approval")
    search_fields = ("office__name", "company__name")
