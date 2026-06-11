import uuid

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import CompanyOffice, Party
from core.policies import can_manage_company, shipment_participates_at_office
from core.request_context import get_current_company, get_current_office
from shipments.models import Shipment
from .models import BankPaymentVerification, Expense, Invoice, InvoiceLine, LedgerEntry, PaymentReceipt
from .permissions import AccountantPermission
from .serializers import (
    ExpenseSerializer,
    InvoiceGenerateSerializer,
    InvoiceSerializer,
    LedgerEntrySerializer,
    PaymentReceiptSerializer,
    VerifyPaymentSerializer,
)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [AccountantPermission]
    queryset = Invoice.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return Invoice.objects.none()
        qs = Invoice.objects.filter(company=company)
        if not can_manage_company(self.request.user, company):
            office = get_current_office()
            if not office:
                return Invoice.objects.none()
            qs = qs.filter(office=office)
        return qs

    @action(detail=False, methods=["post"], url_path="generate")
    @transaction.atomic
    def generate(self, request):
        serializer = InvoiceGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        company = get_current_company() or getattr(request.user, "company", None)
        if not company:
            return Response({"error": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            office = CompanyOffice.objects.get(id=data["office"], company=company)
            party = Party.objects.get(id=data["party"], company=company)
        except (CompanyOffice.DoesNotExist, Party.DoesNotExist):
            return Response({"error": "Invalid office or party."}, status=status.HTTP_400_BAD_REQUEST)

        active_office = get_current_office()
        if not can_manage_company(request.user, company):
            if not active_office or office.id != active_office.id:
                return Response({"error": "You can only generate invoices for your active office."}, status=status.HTTP_400_BAD_REQUEST)

        shipments = Shipment.objects.filter(id__in=data["shipments"], company=company)
        if shipments.count() != len(data["shipments"]):
            return Response({"error": "One or more shipments not found or invalid."}, status=status.HTTP_400_BAD_REQUEST)
        for shipment in shipments:
            if shipment.basis != Shipment.BasisChoices.TBB:
                return Response({"error": f"Shipment {shipment.lr_no} is not TBB and cannot be invoiced."}, status=status.HTTP_400_BAD_REQUEST)
            if not shipment_participates_at_office(shipment, office):
                return Response({"error": f"Shipment {shipment.lr_no} does not participate in the selected billing office."}, status=status.HTTP_400_BAD_REQUEST)
            if shipment.invoice_lines.exists():
                return Response({"error": f"Shipment {shipment.lr_no} is already invoiced."}, status=status.HTTP_400_BAD_REQUEST)

        total_amount = sum(s.final_freight for s in shipments)
        invoice = Invoice.objects.create(
            company=company,
            office=office,
            party=party,
            invoice_no=f"INV-{uuid.uuid4().hex[:8].upper()}",
            status=Invoice.Status.SENT,
            invoice_date=timezone.now().date(),
            due_date=data["due_date"],
            total_amount=total_amount,
        )
        InvoiceLine.objects.bulk_create(
            [
                InvoiceLine(
                    invoice=invoice,
                    shipment=shipment,
                    description=f"Freight charges for LR {shipment.lr_no}",
                    amount=shipment.final_freight,
                )
                for shipment in shipments
            ]
        )
        LedgerEntry.objects.create(
            company=company,
            office=office,
            party=party,
            entry_type=LedgerEntry.EntryType.DEBIT,
            reference_type=LedgerEntry.ReferenceType.INVOICE,
            reference_id=invoice.id,
            debit=total_amount,
            entry_date=invoice.invoice_date,
        )
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class PaymentReceiptViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentReceiptSerializer
    permission_classes = [AccountantPermission]
    queryset = PaymentReceipt.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return PaymentReceipt.objects.none()
        qs = PaymentReceipt.objects.filter(company=company)
        if not can_manage_company(self.request.user, company):
            office = get_current_office()
            if not office:
                return PaymentReceipt.objects.none()
            qs = qs.filter(office=office)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        company = get_current_company() or getattr(self.request.user, "company", None)
        if not company:
            from rest_framework import serializers as drf_serializers

            raise drf_serializers.ValidationError({"company": "Company context required."})
        office = serializer.validated_data.get("office")
        party = serializer.validated_data.get("party")
        active_office = get_current_office()
        if office.company_id != company.id:
            from rest_framework import serializers as drf_serializers

            raise drf_serializers.ValidationError({"office": "Office does not belong to the active company."})
        if party.company_id != company.id:
            from rest_framework import serializers as drf_serializers

            raise drf_serializers.ValidationError({"party": "Party does not belong to the active company."})
        if not can_manage_company(self.request.user, company) and (not active_office or office.id != active_office.id):
            from rest_framework import serializers as drf_serializers

            raise drf_serializers.ValidationError({"office": "You can only create receipts for your active office."})
        receipt = serializer.save(company=company)
        if receipt.payment_mode == PaymentReceipt.PaymentMode.CASH:
            receipt.status = PaymentReceipt.Status.VERIFIED
            receipt.save(update_fields=["status"])
            LedgerEntry.objects.create(
                company=company,
                office=receipt.office,
                party=receipt.party,
                entry_type=LedgerEntry.EntryType.CREDIT,
                reference_type=LedgerEntry.ReferenceType.PAYMENT,
                reference_id=receipt.id,
                credit=receipt.amount,
                entry_date=receipt.received_at.date(),
            )

    @action(detail=True, methods=["post"], url_path="verify-bank-payment")
    @transaction.atomic
    def verify_bank_payment(self, request, pk=None):
        receipt = self.get_object()
        if receipt.status != PaymentReceipt.Status.PENDING:
            return Response({"error": "Receipt is already processed."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        receipt.status = new_status
        receipt.save(update_fields=["status", "updated_at", "updated_by"])
        BankPaymentVerification.objects.create(
            payment_receipt=receipt,
            verified_by=request.user,
            status=new_status,
            notes=serializer.validated_data.get("notes", ""),
        )
        if new_status == BankPaymentVerification.Status.VERIFIED:
            LedgerEntry.objects.create(
                company=receipt.company,
                office=receipt.office,
                party=receipt.party,
                entry_type=LedgerEntry.EntryType.CREDIT,
                reference_type=LedgerEntry.ReferenceType.PAYMENT,
                reference_id=receipt.id,
                credit=receipt.amount,
                entry_date=receipt.received_at.date(),
            )
        return Response(PaymentReceiptSerializer(receipt).data)


class LedgerEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LedgerEntrySerializer
    permission_classes = [AccountantPermission]
    queryset = LedgerEntry.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return LedgerEntry.objects.none()
        qs = LedgerEntry.objects.filter(company=company)
        if not can_manage_company(self.request.user, company):
            office = get_current_office()
            if not office:
                return LedgerEntry.objects.none()
            qs = qs.filter(office=office)
        return qs


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [AccountantPermission]
    queryset = Expense.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return Expense.objects.none()
        qs = Expense.objects.filter(company=company)
        
        # Handle optional filters from query params
        date_param = self.request.query_params.get("date")
        if date_param:
            qs = qs.filter(date=date_param)
            
        office_param = self.request.query_params.get("office")
        if office_param:
            qs = qs.filter(office_id=office_param)

        if not can_manage_company(self.request.user, company):
            office = get_current_office()
            if not office:
                return Expense.objects.none()
            # If the user tries to filter for another office, they are blocked
            if office_param and str(office_param) != str(office.id):
                return Expense.objects.none()
            qs = qs.filter(office=office)
        return qs

    def create(self, request, *args, **kwargs):
        company = get_current_company() or getattr(request.user, "company", None)
        if not company:
            return Response({"error": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        is_many = isinstance(data, list)
        
        serializer = self.get_serializer(data=data, many=is_many)
        serializer.is_valid(raise_exception=True)
        
        if is_many:
            expenses = [Expense(**item, company=company) for item in serializer.validated_data]
            Expense.objects.bulk_create(expenses)
            return Response({"status": "success", "count": len(expenses)}, status=status.HTTP_201_CREATED)
        else:
            serializer.save(company=company)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        company = get_current_company()
        if not company:
            return Response({"error": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset()
        
        date_param = request.query_params.get("date")
        if date_param:
            qs = qs.filter(date=date_param)

        summary = (
            qs.values("date", "office", "office__name")
            .annotate(
                total_amount=Sum("amount"),
                entry_count=Count("id")
            )
            .order_by("-date", "office__name")
        )

        # Add a unique ID for frontend key props
        results = [
            {**item, "id": f"{item['date']}_{item['office']}"}
            for item in summary
        ]
        
        return Response(results)

    @action(detail=False, methods=["get"], url_path="daily-summary")
    def daily_summary(self, request):
        company = get_current_company()
        if not company:
            return Response({"error": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        qs = self.get_queryset()
        
        daily = (
            qs.values("date")
            .annotate(
                total_amount=Sum("amount"),
                entry_count=Count("id"),
                branch_count=Count("office", distinct=True)
            )
            .order_by("-date")
        )
        
        # Add ID for React keys
        results = [
            {**item, "id": str(item['date'])}
            for item in daily
        ]
        
        return Response(results)
