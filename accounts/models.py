from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import AuditBaseModel


class Invoice(AuditBaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SENT = "SENT", _("Sent")
        PAID = "PAID", _("Paid")
        PARTIALLY_PAID = "PARTIALLY_PAID", _("Partially Paid")
        CANCELLED = "CANCELLED", _("Cancelled")

    company = models.ForeignKey("core.Company", related_name="invoices", on_delete=models.CASCADE)
    office = models.ForeignKey("core.CompanyOffice", related_name="invoices", on_delete=models.CASCADE)
    party = models.ForeignKey("core.Party", related_name="invoices", on_delete=models.CASCADE)
    invoice_no = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    invoice_date = models.DateField()
    due_date = models.DateField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name_plural = "Invoices"
        ordering = ["-invoice_date", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["company", "invoice_no"], name="unique_invoice_no_per_company")]


class InvoiceLine(AuditBaseModel):
    invoice = models.ForeignKey(Invoice, related_name="lines", on_delete=models.CASCADE)
    shipment = models.ForeignKey("shipments.Shipment", related_name="invoice_lines", on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name_plural = "Invoice Lines"
        ordering = ["id"]


class PaymentReceipt(AuditBaseModel):
    class PaymentMode(models.TextChoices):
        CASH = "CASH", _("Cash")
        BANK_TRANSFER = "BANK_TRANSFER", _("Bank Transfer")
        CHEQUE = "CHEQUE", _("Cheque")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        VERIFIED = "VERIFIED", _("Verified")
        REJECTED = "REJECTED", _("Rejected")

    company = models.ForeignKey("core.Company", related_name="payment_receipts", on_delete=models.CASCADE)
    office = models.ForeignKey("core.CompanyOffice", related_name="payment_receipts", on_delete=models.CASCADE)
    party = models.ForeignKey("core.Party", related_name="payment_receipts", on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices)
    reference_no = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    received_at = models.DateTimeField()

    class Meta:
        verbose_name_plural = "Payment Receipts"
        ordering = ["-received_at"]


class BankPaymentVerification(AuditBaseModel):
    class Status(models.TextChoices):
        VERIFIED = "VERIFIED", _("Verified")
        REJECTED = "REJECTED", _("Rejected")

    payment_receipt = models.OneToOneField(PaymentReceipt, related_name="verification", on_delete=models.CASCADE)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="verified_payments", on_delete=models.PROTECT)
    verified_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Bank Payment Verifications"


class LedgerEntry(AuditBaseModel):
    class EntryType(models.TextChoices):
        DEBIT = "DEBIT", _("Debit")
        CREDIT = "CREDIT", _("Credit")

    class ReferenceType(models.TextChoices):
        INVOICE = "INVOICE", _("Invoice")
        PAYMENT = "PAYMENT", _("Payment")
        SHIPMENT = "SHIPMENT", _("Shipment")

    company = models.ForeignKey("core.Company", related_name="ledger_entries", on_delete=models.CASCADE)
    office = models.ForeignKey("core.CompanyOffice", related_name="ledger_entries", on_delete=models.CASCADE)
    party = models.ForeignKey("core.Party", related_name="ledger_entries", on_delete=models.CASCADE)
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    reference_type = models.CharField(max_length=20, choices=ReferenceType.choices)
    reference_id = models.CharField(max_length=26)
    debit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    entry_date = models.DateField()

    class Meta:
        verbose_name_plural = "Ledger Entries"
        ordering = ["-entry_date", "-created_at"]


class Expense(AuditBaseModel):
    company = models.ForeignKey("core.Company", related_name="expenses", on_delete=models.CASCADE)
    office = models.ForeignKey("core.CompanyOffice", related_name="expenses", on_delete=models.CASCADE)
    date = models.DateField()
    category = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name_plural = "Expenses"
        ordering = ["-date", "-created_at"]
