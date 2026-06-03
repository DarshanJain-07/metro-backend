from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from .models import Invoice, InvoiceLine, PaymentReceipt, BankPaymentVerification, LedgerEntry
from .serializers import (
    InvoiceSerializer, InvoiceGenerateSerializer, PaymentReceiptSerializer,
    BankPaymentVerificationSerializer, VerifyPaymentSerializer, LedgerEntrySerializer
)
from .permissions import AccountantPermission
from dockets.models import Docket
from core.models import Branch, Party
from core.request_context import get_current_company

class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [AccountantPermission]
    queryset = Invoice.objects.all()

    @action(detail=False, methods=['post'], url_path='generate')
    @transaction.atomic
    def generate(self, request):
        serializer = InvoiceGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        data = serializer.validated_data
        party_id = data['party']
        branch_id = data['branch']
        docket_ids = data['dockets']
        due_date = data['due_date']
        
        company = get_current_company() or getattr(request.user, 'company', None)
        if not company:
             return Response({"error": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            branch = Branch.objects.get(id=branch_id, company=company)
            party = Party.objects.get(id=party_id, company=company)
        except (Branch.DoesNotExist, Party.DoesNotExist):
             return Response({"error": "Invalid branch or party."}, status=status.HTTP_400_BAD_REQUEST)

        dockets = Docket.objects.filter(id__in=docket_ids, company=company)
        if dockets.count() != len(docket_ids):
            return Response({"error": "One or more dockets not found or invalid."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Enforce TBB rule
        for docket in dockets:
            if docket.payment_type != Docket.PaymentTypeChoices.TBB:
                return Response({"error": f"Docket {docket.docket_no} is not TBB and cannot be invoiced."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate total
        total_amount = sum(d.final_freight for d in dockets)
        
        import uuid
        invoice_no = f"INV-{uuid.uuid4().hex[:8].upper()}"
        
        invoice = Invoice.objects.create(
            company=company,
            branch=branch,
            party=party,
            invoice_no=invoice_no,
            status=Invoice.Status.SENT,
            invoice_date=timezone.now().date(),
            due_date=due_date,
            total_amount=total_amount
        )
        
        lines = []
        for docket in dockets:
            lines.append(InvoiceLine(
                invoice=invoice,
                docket=docket,
                description=f"Freight charges for Docket {docket.docket_no}",
                amount=docket.final_freight
            ))
        InvoiceLine.objects.bulk_create(lines)
        
        LedgerEntry.objects.create(
            company=company,
            branch=branch,
            party=party,
            entry_type=LedgerEntry.EntryType.DEBIT,
            reference_type=LedgerEntry.ReferenceType.INVOICE,
            reference_id=invoice.id,
            debit=total_amount,
            entry_date=invoice.invoice_date
        )
        
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class PaymentReceiptViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentReceiptSerializer
    permission_classes = [AccountantPermission]
    queryset = PaymentReceipt.objects.all()

    @transaction.atomic
    def perform_create(self, serializer):
        company = get_current_company() or getattr(self.request.user, 'company', None)
        receipt = serializer.save(company=company)

        # Automatically verify CASH payments and generate ledger entry
        if receipt.payment_mode == PaymentReceipt.PaymentMode.CASH:
            receipt.status = PaymentReceipt.Status.VERIFIED
            receipt.save(update_fields=['status'])
            
            LedgerEntry.objects.create(
                company=company,
                branch=receipt.branch,
                party=receipt.party,
                entry_type=LedgerEntry.EntryType.CREDIT,
                reference_type=LedgerEntry.ReferenceType.PAYMENT,
                reference_id=receipt.id,
                credit=receipt.amount,
                entry_date=receipt.received_at.date()
            )

    @action(detail=True, methods=['post'], url_path='verify-bank-payment')
    @transaction.atomic
    def verify_bank_payment(self, request, pk=None):
        receipt = self.get_object()
        
        if receipt.status != PaymentReceipt.Status.PENDING:
            return Response({"error": "Receipt is already processed."}, status=status.HTTP_400_BAD_REQUEST)
            
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        new_status = serializer.validated_data['status']
        notes = serializer.validated_data.get('notes', '')
        
        receipt.status = new_status
        receipt.save(update_fields=['status', 'updated_at', 'updated_by'])
        
        BankPaymentVerification.objects.create(
            payment_receipt=receipt,
            verified_by=request.user,
            status=new_status,
            notes=notes
        )
        
        if new_status == BankPaymentVerification.Status.VERIFIED:
            LedgerEntry.objects.create(
                company=receipt.company,
                branch=receipt.branch,
                party=receipt.party,
                entry_type=LedgerEntry.EntryType.CREDIT,
                reference_type=LedgerEntry.ReferenceType.PAYMENT,
                reference_id=receipt.id,
                credit=receipt.amount,
                entry_date=receipt.received_at.date()
            )
            
        return Response(PaymentReceiptSerializer(receipt).data)


class LedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LedgerEntrySerializer
    permission_classes = [AccountantPermission]
    queryset = LedgerEntry.objects.all()
