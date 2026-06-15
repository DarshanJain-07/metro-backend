import uuid
from datetime import datetime, date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Sum
from django.utils import timezone
from django.db.models.functions import TruncDate
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


class CashbookViewSet(viewsets.ViewSet):
    permission_classes = [AccountantPermission]
    permission_resource = "expense"

    def list(self, request):
        company = get_current_company()
        if not company:
            return Response({"error": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        office = get_current_office()
        # If user can manage company, they might want all offices or a specific one
        requested_office_id = request.query_params.get("office")
        if requested_office_id and can_manage_company(request.user, company):
            office_filter = requested_office_id
        elif office:
            office_filter = office.id
        else:
            if not can_manage_company(request.user, company):
                return Response({"error": "Office context required."}, status=status.HTTP_400_BAD_REQUEST)
            office_filter = None

        start_date_param = request.query_params.get("start_date")
        end_date_param = request.query_params.get("end_date")

        if not start_date_param or not end_date_param:
            # Default to current month
            today = timezone.now().date()
            start_date = today.replace(day=1)
            end_date = today
        else:
            try:
                start_date = datetime.strptime(start_date_param, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_param, "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Calculate Opening Balance (before start_date)
        # Income from Shipments
        shipment_income_query = Shipment.objects.filter(
            company=company,
            date__lt=start_date,
            payment_type__in=[Shipment.PaymentTypeChoices.CASH, Shipment.PaymentTypeChoices.BANK],
        )
        if office_filter:
            shipment_income_query = shipment_income_query.filter(origin_office_id=office_filter)
        
        opening_shipment_income = shipment_income_query.aggregate(total=Sum("advance_amount"))["total"] or Decimal("0.00")

        # Income from PaymentReceipts
        receipt_income_query = PaymentReceipt.objects.filter(
            company=company,
            received_at__date__lt=start_date,
            payment_mode__in=[PaymentReceipt.PaymentMode.CASH, PaymentReceipt.PaymentMode.BANK_TRANSFER],
            status=PaymentReceipt.Status.VERIFIED,
        )
        if office_filter:
            receipt_income_query = receipt_income_query.filter(office_id=office_filter)
        
        opening_receipt_income = receipt_income_query.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Expenses
        expense_query = Expense.objects.filter(
            company=company,
            date__lt=start_date,
        )
        if office_filter:
            expense_query = expense_query.filter(office_id=office_filter)
        
        opening_expenses = expense_query.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        opening_balance = opening_shipment_income + opening_receipt_income - opening_expenses

        # 2. Get Daily Totals for the range
        # Daily Shipment Income
        daily_shipment_income = Shipment.objects.filter(
            company=company,
            date__range=[start_date, end_date],
            payment_type__in=[Shipment.PaymentTypeChoices.CASH, Shipment.PaymentTypeChoices.BANK],
        )
        if office_filter:
            daily_shipment_income = daily_shipment_income.filter(origin_office_id=office_filter)
        
        daily_shipment_income = daily_shipment_income.values("date").annotate(total=Sum("advance_amount")).order_by("date")

        # Daily Receipt Income
        daily_receipt_income = PaymentReceipt.objects.filter(
            company=company,
            received_at__date__range=[start_date, end_date],
            payment_mode__in=[PaymentReceipt.PaymentMode.CASH, PaymentReceipt.PaymentMode.BANK_TRANSFER],
            status=PaymentReceipt.Status.VERIFIED,
        )
        if office_filter:
            daily_receipt_income = daily_receipt_income.filter(office_id=office_filter)
        
        daily_receipt_income = daily_receipt_income.annotate(date=TruncDate('received_at')).values("date").annotate(total=Sum("amount")).order_by("date")

        # Daily Expenses
        daily_expenses = Expense.objects.filter(
            company=company,
            date__range=[start_date, end_date],
        )
        if office_filter:
            daily_expenses = daily_expenses.filter(office_id=office_filter)
        
        daily_expenses = daily_expenses.values("date").annotate(total=Sum("amount")).order_by("date")

        # Combine into a map by date
        data_by_date = {}
        curr = start_date
        while curr <= end_date:
            data_by_date[curr] = {"income": Decimal("0.00"), "expense": Decimal("0.00")}
            curr += timedelta(days=1)

        for item in daily_shipment_income:
            data_by_date[item["date"]]["income"] += item["total"]
        
        for item in daily_receipt_income:
            d = item["date"]
            if isinstance(d, str):
                d = datetime.strptime(d, "%Y-%m-%d").date()
            if d in data_by_date:
                data_by_date[d]["income"] += item["total"]
        
        for item in daily_expenses:
            data_by_date[item["date"]]["expense"] += item["total"]

        # 3. Calculate Running Balance
        results = []
        running_balance = opening_balance
        
        # Sort dates to ensure sequence
        sorted_dates = sorted(data_by_date.keys())
        
        total_income = Decimal("0.00")
        total_expense = Decimal("0.00")

        for d in sorted_dates:
            day_income = data_by_date[d]["income"]
            day_expense = data_by_date[d]["expense"]
            
            day_opening = running_balance
            day_closing = day_opening + day_income - day_expense
            
            results.append({
                "date": d.isoformat(),
                "opening_balance": float(day_opening),
                "income": float(day_income),
                "expense": float(day_expense),
                "closing_balance": float(day_closing),
            })
            
            running_balance = day_closing
            total_income += day_income
            total_expense += day_expense

        return Response({
            "summary": {
                "opening_balance": float(opening_balance),
                "total_income": float(total_income),
                "total_expense": float(total_expense),
                "closing_balance": float(running_balance),
            },
            "daily_records": results[::-1] # Newest first for display
        })


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [AccountantPermission]
    permission_resource = "invoice"
    action_permissions = {"generate": "invoice:generate"}
    queryset = Invoice.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return Invoice.objects.none()
        qs = Invoice.objects.filter(company=company).select_related("office", "party").prefetch_related("lines")
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

        shipments = Shipment.objects.filter(id__in=data["shipments"], company=company).annotate(
            is_billed=Exists(InvoiceLine.objects.filter(shipment=OuterRef("pk")))
        )
        if shipments.count() != len(data["shipments"]):
            return Response({"error": "One or more shipments not found or invalid."}, status=status.HTTP_400_BAD_REQUEST)
        for shipment in shipments:
            if shipment.basis != Shipment.BasisChoices.TBB:
                return Response({"error": f"Shipment {shipment.lr_no} is not TBB and cannot be invoiced."}, status=status.HTTP_400_BAD_REQUEST)
            if not shipment_participates_at_office(shipment, office):
                return Response({"error": f"Shipment {shipment.lr_no} does not participate in the selected billing office."}, status=status.HTTP_400_BAD_REQUEST)
            if shipment.is_billed:
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
        for shipment in shipments:
            InvoiceLine.objects.create(
                invoice=invoice,
                shipment=shipment,
                description=f"Freight charges for LR {shipment.lr_no}",
                amount=shipment.final_freight,
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
    permission_resource = "payment"
    action_permissions = {"verify_bank_payment": "payment:verify"}
    queryset = PaymentReceipt.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return PaymentReceipt.objects.none()
        qs = PaymentReceipt.objects.filter(company=company).select_related("office", "party")
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
    permission_resource = "invoice"
    queryset = LedgerEntry.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return LedgerEntry.objects.none()
        qs = LedgerEntry.objects.filter(company=company).select_related("office", "party")
        if not can_manage_company(self.request.user, company):
            office = get_current_office()
            if not office:
                return LedgerEntry.objects.none()
            qs = qs.filter(office=office)
        return qs


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [AccountantPermission]
    permission_resource = "expense"
    action_permissions = {
        "summary": "expense:view",
        "daily_summary": "expense:view",
    }
    queryset = Expense.objects.all()

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return Expense.objects.none()
        qs = Expense.objects.filter(company=company).select_related("office")
        
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
            created_expenses = []
            for expense_data in serializer.validated_data:
                created_expenses.append(Expense.objects.create(**expense_data, company=company))
            return Response({"status": "success", "count": len(created_expenses)}, status=status.HTTP_201_CREATED)
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

        return Response(summary)

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
        
        return Response(daily)
