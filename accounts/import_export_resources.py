from collections import OrderedDict

from import_export import fields

from accounts.models import Expense, Invoice
from core.import_export_resources import (
    CompanyScopedResourceMixin,
    ImportExportBaseResource,
    ScopedForeignKeyWidget,
)
from core.models import CompanyOffice, Party


class InvoiceResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    office = fields.Field(
        column_name="office",
        attribute="office",
        widget=ScopedForeignKeyWidget(CompanyOffice, lookup_fields=("id", "name"), company_scoped=True),
    )
    party = fields.Field(
        column_name="party",
        attribute="party",
        widget=ScopedForeignKeyWidget(Party, lookup_fields=("id", "name"), company_scoped=True),
    )

    class Meta(ImportExportBaseResource.Meta):
        model = Invoice
        fields = (
            "id",
            "invoice_no",
            "office",
            "party",
            "status",
            "invoice_date",
            "due_date",
            "total_amount",
            "paid_amount",
        )
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        invoice_no = row.get("invoice_no")
        if invoice_no:
            return self.get_company_queryset().filter(invoice_no__iexact=invoice_no).first()
        return None


class ExpenseResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    office = fields.Field(
        column_name="office",
        attribute="office",
        widget=ScopedForeignKeyWidget(CompanyOffice, lookup_fields=("id", "name"), company_scoped=True),
    )

    class Meta(ImportExportBaseResource.Meta):
        model = Expense
        fields = ("id", "office", "date", "category", "amount", "notes")
        export_order = fields


ACCOUNTING_IMPORT_EXPORT_RESOURCES = OrderedDict(
    [
        ("invoices", InvoiceResource),
        ("expenses", ExpenseResource),
    ]
)
