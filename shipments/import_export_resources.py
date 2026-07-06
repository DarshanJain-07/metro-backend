from collections import OrderedDict

from import_export import fields
from import_export.widgets import BooleanWidget

from core.import_export_resources import (
    CompanyScopedResourceMixin,
    ImportExportBaseResource,
    ScopedForeignKeyWidget,
)
from core.models import City, CompanyOffice
from shipments.models import OfficeRatePolicy, RateCard, RateRule


class RateCardResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    is_default = fields.Field(attribute="is_default", widget=BooleanWidget())
    is_active = fields.Field(attribute="is_active", widget=BooleanWidget())

    class Meta(ImportExportBaseResource.Meta):
        model = RateCard
        fields = ("id", "name", "is_default", "effective_from", "effective_to", "is_active")
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        name = row.get("name")
        if name:
            return self.get_company_queryset().filter(name__iexact=name).first()
        return None


class RateRuleResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    rate_card = fields.Field(
        column_name="rate_card",
        attribute="rate_card",
        widget=ScopedForeignKeyWidget(RateCard, lookup_fields=("id", "name"), company_scoped=True),
    )
    origin_city = fields.Field(
        column_name="origin_city",
        attribute="origin_city",
        widget=ScopedForeignKeyWidget(City, lookup_fields=("id", "name")),
    )
    destination_city = fields.Field(
        column_name="destination_city",
        attribute="destination_city",
        widget=ScopedForeignKeyWidget(City, lookup_fields=("id", "name")),
    )
    origin_office = fields.Field(
        column_name="origin_office",
        attribute="origin_office",
        widget=ScopedForeignKeyWidget(CompanyOffice, lookup_fields=("id", "name"), company_scoped=True),
    )
    destination_office = fields.Field(
        column_name="destination_office",
        attribute="destination_office",
        widget=ScopedForeignKeyWidget(CompanyOffice, lookup_fields=("id", "name"), company_scoped=True),
    )

    class Meta(ImportExportBaseResource.Meta):
        model = RateRule
        fields = (
            "id",
            "rate_card",
            "origin_city",
            "destination_city",
            "origin_office",
            "destination_office",
            "basis",
            "rate_type",
            "rate",
            "min_charge",
            "delivery_charge",
            "is_active",
        )
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        if not row.get("rate_card") or not row.get("origin_city") or not row.get("destination_city"):
            return None
        rate_card = self.clean_field("rate_card", row, company=self.company)
        origin_city = self.clean_field("origin_city", row)
        destination_city = self.clean_field("destination_city", row)
        origin_office = self.clean_field("origin_office", row, company=self.company) if row.get("origin_office") else None
        destination_office = (
            self.clean_field("destination_office", row, company=self.company)
            if row.get("destination_office")
            else None
        )
        return self.get_company_queryset().filter(
            rate_card=rate_card,
            origin_city=origin_city,
            destination_city=destination_city,
            origin_office=origin_office,
            destination_office=destination_office,
            basis=row.get("basis"),
            rate_type=row.get("rate_type"),
        ).first()


class OfficeRatePolicyResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    office = fields.Field(
        column_name="office",
        attribute="office",
        widget=ScopedForeignKeyWidget(CompanyOffice, lookup_fields=("id", "name"), company_scoped=True),
    )
    can_override_rate = fields.Field(attribute="can_override_rate", widget=BooleanWidget())
    requires_approval = fields.Field(attribute="requires_approval", widget=BooleanWidget())

    class Meta(ImportExportBaseResource.Meta):
        model = OfficeRatePolicy
        fields = ("id", "office", "can_override_rate", "max_discount_percent", "requires_approval")
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        office = self.clean_field("office", row, company=self.company) if row.get("office") else None
        if office:
            return self.get_company_queryset().filter(office=office).first()
        return None


RATE_IMPORT_EXPORT_RESOURCES = OrderedDict(
    [
        ("rate-cards", RateCardResource),
        ("rate-rules", RateRuleResource),
        ("office-rate-policies", OfficeRatePolicyResource),
    ]
)
