from rest_framework import serializers

from core.request_context import get_current_company
from .models import BankPaymentVerification, Invoice, InvoiceLine, LedgerEntry, PaymentReceipt


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ["id", "shipment", "description", "amount"]


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    party_name = serializers.CharField(source="party.name", read_only=True)
    office_name = serializers.CharField(source="office.name", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_no",
            "company",
            "office",
            "party",
            "party_name",
            "office_name",
            "status",
            "invoice_date",
            "due_date",
            "total_amount",
            "paid_amount",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["company", "invoice_no"]


class InvoiceGenerateSerializer(serializers.Serializer):
    party = serializers.CharField()
    office = serializers.CharField()
    shipments = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    due_date = serializers.DateField()


class PaymentReceiptSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    office_name = serializers.CharField(source="office.name", read_only=True)

    class Meta:
        model = PaymentReceipt
        fields = [
            "id",
            "company",
            "office",
            "party",
            "party_name",
            "office_name",
            "amount",
            "payment_mode",
            "reference_no",
            "status",
            "received_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["company", "status"]

    def validate(self, data):
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})
        office = data.get("office", getattr(self.instance, "office", None))
        party = data.get("party", getattr(self.instance, "party", None))
        if office and office.company != company:
            raise serializers.ValidationError({"office": "Office does not belong to the active company."})
        if party and party.company != company:
            raise serializers.ValidationError({"party": "Party does not belong to the active company."})
        return data


class BankPaymentVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankPaymentVerification
        fields = ["id", "payment_receipt", "verified_by", "verified_at", "status", "notes"]
        read_only_fields = ["payment_receipt", "verified_by", "verified_at"]


class VerifyPaymentSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BankPaymentVerification.Status.choices)
    notes = serializers.CharField(required=False, allow_blank=True)


class LedgerEntrySerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name", read_only=True)
    office_name = serializers.CharField(source="office.name", read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "company",
            "office",
            "party",
            "party_name",
            "office_name",
            "entry_type",
            "reference_type",
            "reference_id",
            "debit",
            "credit",
            "entry_date",
            "created_at",
        ]
        read_only_fields = ["company"]
