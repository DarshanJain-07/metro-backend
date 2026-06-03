from rest_framework import serializers
from .models import Invoice, InvoiceLine, PaymentReceipt, BankPaymentVerification, LedgerEntry

class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ['id', 'docket', 'description', 'amount']

class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    party_name = serializers.CharField(source='party.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_no', 'company', 'branch', 'party', 'party_name', 'branch_name',
            'status', 'invoice_date', 'due_date', 'total_amount', 'paid_amount', 'lines',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['company', 'invoice_no']

class InvoiceGenerateSerializer(serializers.Serializer):
    party = serializers.CharField() # Party ID
    branch = serializers.CharField() # Branch ID
    dockets = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False
    )
    due_date = serializers.DateField()

class PaymentReceiptSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source='party.name', read_only=True)

    class Meta:
        model = PaymentReceipt
        fields = [
            'id', 'company', 'branch', 'party', 'party_name', 'amount',
            'payment_mode', 'reference_no', 'status', 'received_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['company', 'status']

class BankPaymentVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankPaymentVerification
        fields = ['id', 'payment_receipt', 'verified_by', 'verified_at', 'status', 'notes']
        read_only_fields = ['payment_receipt', 'verified_by', 'verified_at']

class VerifyPaymentSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BankPaymentVerification.Status.choices)
    notes = serializers.CharField(required=False, allow_blank=True)

class LedgerEntrySerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source='party.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            'id', 'company', 'branch', 'party', 'party_name', 'branch_name',
            'entry_type', 'reference_type', 'reference_id', 'debit', 'credit',
            'entry_date', 'created_at'
        ]
        read_only_fields = ['company']
