from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from accounts.import_export_resources import ExpenseResource, InvoiceResource
from accounts.models import Expense, Invoice
from core.import_export_admin import RequestContextResourceAdminMixin


@admin.register(Invoice)
class InvoiceAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [InvoiceResource]
    list_display = ("invoice_no", "company", "office", "party", "status", "invoice_date", "total_amount", "paid_amount")
    list_filter = ("status", "company", "office", "invoice_date")
    search_fields = ("invoice_no", "party__name", "office__name")


@admin.register(Expense)
class ExpenseAdmin(RequestContextResourceAdminMixin, ImportExportModelAdmin):
    resource_classes = [ExpenseResource]
    list_display = ("date", "company", "office", "category", "amount")
    list_filter = ("company", "office", "date", "category")
    search_fields = ("category", "notes", "office__name")
