import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from accounts.models import Invoice, InvoiceLine, LedgerEntry
from accounts.permissions import AccountantPermission
from accounts.serializers import InvoiceSerializer
from core.models import CompanyOffice, Party
from core.policies import can, can_manage_company, shipment_participates_at_office
from core.request_context import get_current_company, get_current_office
from core.viewsets import IdempotentCreateMixin, OptimisticConcurrencyMixin, SoftDeleteMixin, TenantOfficeScopedQuerysetMixin
from .admin_serializers import OfficeRatePolicySerializer, RateCardSerializer, RateRuleSerializer
from .filters import ShipmentFilter
from .models import DeliveryAssignment, OfficeRatePolicy, RateCard, RateRule, Shipment, ShipmentEvent, ShipmentLineItem
from .permissions import IsCompanyAdminPermission, StrictActionPermission
from .serializers import (
    DeliveryAssignmentSerializer,
    ProofOfDeliverySerializer,
    ShipmentEventSerializer,
    ShipmentListSerializer,
    ShipmentSerializer,
)
from .services import ShipmentWorkflowService, lookup_rate
from .utils import generate_lr_no


class RateCardViewSet(viewsets.ModelViewSet):
    queryset = RateCard.objects.all()
    serializer_class = RateCardSerializer
    permission_classes = [IsCompanyAdminPermission]

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return RateCard.objects.none()
        return RateCard.objects.filter(company=company)

    def perform_create(self, serializer):
        serializer.save(company=get_current_company())


class RateRuleViewSet(viewsets.ModelViewSet):
    queryset = RateRule.objects.all()
    serializer_class = RateRuleSerializer
    permission_classes = [IsCompanyAdminPermission]

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return RateRule.objects.none()
        return RateRule.objects.filter(rate_card__company=company).select_related(
            "rate_card",
            "origin_city",
            "destination_city",
            "origin_office",
            "destination_office",
        ).order_by("id")


class OfficeRatePolicyViewSet(viewsets.ModelViewSet):
    queryset = OfficeRatePolicy.objects.all()
    serializer_class = OfficeRatePolicySerializer
    permission_classes = [IsCompanyAdminPermission]

    def get_queryset(self):
        company = get_current_company()
        if not company:
            return OfficeRatePolicy.objects.none()
        return OfficeRatePolicy.objects.filter(company=company)

    def perform_create(self, serializer):
        serializer.save(company=get_current_company())


class ShipmentViewSet(
    IdempotentCreateMixin,
    OptimisticConcurrencyMixin,
    TenantOfficeScopedQuerysetMixin,
    SoftDeleteMixin,
    viewsets.ModelViewSet,
):
    queryset = Shipment.objects.none()
    serializer_class = ShipmentSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["lr_no", "consignor_name", "consignee_name", "consignor_city__name", "consignee_city__name"]
    ordering_fields = "__all__"
    ordering = ["-created_at"]
    filterset_class = ShipmentFilter
    permission_classes = [StrictActionPermission]
    office_scope_permission = "shipments.view_all_offices"
    office_scope_fields = ("origin_office", "destination_office", "events__office")

    def get_serializer_class(self):
        if self.action == "list":
            return ShipmentListSerializer
        return ShipmentSerializer

    def get_queryset(self):
        qs = Shipment.unscoped_objects.filter(is_active=True).select_related(
            "company",
            "origin_office",
            "destination_office",
            "from_city",
            "to_city",
            "consignor_city",
            "consignee_city",
            "created_by",
            "updated_by",
        )
        if self.action in ["retrieve", "update", "partial_update"]:
            qs = qs.prefetch_related("line_items", "events")
        qs = self.apply_office_scope(qs)
        if self.action == "list":
            requested_origin_office = self.request.query_params.get("origin_office")
            office = get_current_office()
            if requested_origin_office:
                qs = qs.filter(origin_office_id=requested_origin_office)
            elif office:
                qs = qs.filter(origin_office=office)
        return qs.distinct()

    def perform_create(self, serializer):
        company = get_current_company()
        if not company:
            from rest_framework import serializers as drf_serializers

            raise drf_serializers.ValidationError({"company": "Active company context required."})
        lr_no = generate_lr_no(serializer.validated_data.get("date"), company)
        shipment = serializer.save(
            company=company,
            lr_no=lr_no,
            status=Shipment.StatusChoices.BOOKED,
            **self.get_idempotency_save_kwargs(),
        )
        ShipmentWorkflowService.record_event(shipment, ShipmentEvent.EventType.BOOKED, self.request.user, office=shipment.origin_office)

    @action(detail=False, methods=["get"], url_path="suggested-rate")
    def suggested_rate(self, request):
        origin_office_id = request.query_params.get("origin_office")
        dest_office_id = request.query_params.get("destination_office")
        basis = request.query_params.get("basis")
        if not origin_office_id or not dest_office_id:
            return Response({"detail": "origin_office and destination_office are required."}, status=status.HTTP_400_BAD_REQUEST)

        from core.models import CompanyOffice

        try:
            company = get_current_company()
            origin_office = CompanyOffice.objects.get(pk=origin_office_id, company=company)
            dest_office = CompanyOffice.objects.get(pk=dest_office_id, company=company)
        except CompanyOffice.DoesNotExist:
            return Response({"detail": "Office not found."}, status=status.HTTP_404_NOT_FOUND)

        if not can_manage_company(request.user, company) and not can(
            request.user,
            "shipment:create",
            company=company,
            office=origin_office,
        ):
            return Response({"detail": "You do not have permission to view rates for this origin office."}, status=status.HTTP_403_FORBIDDEN)

        rule = lookup_rate(get_current_company(), origin_office, dest_office, basis)
        if not rule:
            return Response({"rate": None, "detail": "No rate rule found for this route."})
        return Response(
            {
                "rate": float(rule.rate),
                "rate_type": rule.rate_type,
                "min_charge": float(rule.min_charge),
                "delivery_charge": float(rule.delivery_charge),
                "rule_id": rule.id,
            }
        )

    @action(detail=False, methods=["post"], url_path="bill", url_name="bill", permission_classes=[AccountantPermission])
    @transaction.atomic
    def bill_selected_shipments(self, request):
        company = get_current_company() or getattr(request.user, "company", None)
        if not company:
            return Response({"detail": "Company context required."}, status=status.HTTP_400_BAD_REQUEST)

        shipment_ids = request.data.get("shipment_ids") or request.data.get("shipments") or []
        if not isinstance(shipment_ids, list) or not shipment_ids:
            return Response({"detail": "shipment_ids must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

        due_date = timezone.now().date()
        if request.data.get("due_date"):
            due_date = parse_date(str(request.data["due_date"]))
            if not due_date:
                return Response({"detail": "due_date must be in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)

        office = get_current_office()
        office_id = request.data.get("office")
        if office_id:
            try:
                office = CompanyOffice.objects.get(id=office_id, company=company)
            except CompanyOffice.DoesNotExist:
                return Response({"detail": "Invalid office."}, status=status.HTTP_400_BAD_REQUEST)

        shipments = list(
            Shipment.unscoped_objects.filter(id__in=shipment_ids, company=company)
            .select_related("origin_office", "destination_office")
            .prefetch_related("invoice_lines")
        )
        if len(shipments) != len(set(shipment_ids)):
            return Response({"detail": "One or more shipments not found or invalid."}, status=status.HTTP_400_BAD_REQUEST)

        if not office:
            origin_office_ids = {shipment.origin_office_id for shipment in shipments}
            if len(origin_office_ids) != 1:
                return Response({"detail": "office is required when selected shipments have multiple origin offices."}, status=status.HTTP_400_BAD_REQUEST)
            office = shipments[0].origin_office

        if not can_manage_company(request.user, company):
            active_office = get_current_office()
            if not active_office or office.id != active_office.id:
                return Response({"detail": "You can only generate bills for your active office."}, status=status.HTTP_400_BAD_REQUEST)

        explicit_party = None
        if request.data.get("party"):
            explicit_party = Party.objects.filter(id=request.data["party"], company=company).first()
            if not explicit_party:
                return Response({"detail": "Invalid party."}, status=status.HTTP_400_BAD_REQUEST)

        invoices_by_party = {}
        for shipment in shipments:
            if shipment.basis != Shipment.BasisChoices.TBB:
                return Response({"detail": f"Shipment {shipment.lr_no} is not TBB and cannot be billed."}, status=status.HTTP_400_BAD_REQUEST)
            if shipment.invoice_lines.exists():
                return Response({"detail": f"Shipment {shipment.lr_no} is already billed."}, status=status.HTTP_400_BAD_REQUEST)
            if not shipment_participates_at_office(shipment, office):
                return Response({"detail": f"Shipment {shipment.lr_no} does not participate in the billing office."}, status=status.HTTP_400_BAD_REQUEST)

            party = explicit_party or self._infer_billing_party(shipment, company)
            if not party:
                return Response({"detail": f"Billing party could not be resolved for shipment {shipment.lr_no}."}, status=status.HTTP_400_BAD_REQUEST)
            invoices_by_party.setdefault(party, []).append(shipment)

        invoices = []
        for party, party_shipments in invoices_by_party.items():
            total_amount = sum(shipment.final_freight for shipment in party_shipments)
            invoice = Invoice.objects.create(
                company=company,
                office=office,
                party=party,
                invoice_no=f"INV-{uuid.uuid4().hex[:8].upper()}",
                status=Invoice.Status.SENT,
                invoice_date=timezone.now().date(),
                due_date=due_date,
                total_amount=total_amount,
            )
            for shipment in party_shipments:
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
            invoices.append(invoice)

        return Response({"invoices": InvoiceSerializer(invoices, many=True).data}, status=status.HTTP_201_CREATED)

    def _infer_billing_party(self, shipment, company):
        names = [shipment.gst_party, shipment.consignor_name, shipment.consignee_name]
        for name in names:
            if not name:
                continue
            party = Party.objects.filter(company=company, name=name).first()
            if party:
                return party
        return None

    @action(detail=False, methods=["post"])
    def preview(self, request):
        line_items = request.data.get("line_items", [])
        additional_charges = Decimal(str(request.data.get("additional_charges", 0)))
        delivery_charge = Decimal(str(request.data.get("delivery_charge", 0)))
        advance_amount = Decimal(str(request.data.get("advance_amount", 0)))
        calculated_line_items = []
        total_freight = Decimal("0.00")
        total_pieces = 0
        total_actual_weight = Decimal("0.00")
        total_charged_weight = Decimal("0.00")
        for item in line_items:
            rate_type = item.get("rate_type", ShipmentLineItem.RateTypeChoices.PER_KG)
            pieces = int(item.get("pieces", 0))
            actual_weight = Decimal(str(item.get("actual_weight", 0)))
            charged_weight = Decimal(str(item.get("charged_weight", 0)))
            rate = Decimal(str(item.get("rate", 0)))
            if rate_type == ShipmentLineItem.RateTypeChoices.PER_PIECE:
                charge = (rate * pieces).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            elif rate_type == ShipmentLineItem.RateTypeChoices.PER_KG:
                charge = (rate * charged_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                charge = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            calculated_line_items.append({"id": item.get("id"), "charge": float(charge)})
            total_freight += charge
            total_pieces += pieces
            total_actual_weight += actual_weight
            total_charged_weight += charged_weight
        final_freight = total_freight + additional_charges + delivery_charge
        return Response(
            {
                "line_items": calculated_line_items,
                "freight": float(total_freight),
                "total_packages": total_pieces,
                "total_actual_weight": float(total_actual_weight),
                "total_charge_weight": float(total_charged_weight),
                "final_freight": float(final_freight),
                "remaining_balance": float(final_freight - advance_amount),
            }
        )

    @action(detail=True, methods=["post"])
    def book(self, request, pk=None):
        return self._workflow_response(lambda shipment: ShipmentWorkflowService.book_shipment(shipment, request.user))

    @action(detail=True, methods=["post"], url_path="dispatch", url_name="dispatch")
    def dispatch_shipment(self, request, pk=None):
        return self._workflow_response(lambda shipment: ShipmentWorkflowService.dispatch(shipment, request.user, notes=request.data.get("notes")))

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        return self._workflow_response(lambda shipment: ShipmentWorkflowService.receive(shipment, request.user, notes=request.data.get("notes")))

    @action(detail=True, methods=["post"], url_path="assign-delivery")
    def assign_delivery(self, request, pk=None):
        shipment = self.get_object()
        delivery_user_id = request.data.get("delivery_user")
        if not delivery_user_id:
            return Response({"detail": "delivery_user is required"}, status=status.HTTP_400_BAD_REQUEST)
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            delivery_user = User.objects.get(pk=delivery_user_id)
            assignment = ShipmentWorkflowService.assign_delivery(shipment, delivery_user, request.user)
            return Response(DeliveryAssignmentSerializer(assignment).data)
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="mark-delivered")
    def mark_delivered(self, request, pk=None):
        shipment = self.get_object()
        serializer = ProofOfDeliverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ShipmentWorkflowService.mark_delivered(shipment, serializer.validated_data, request.user)
            return Response(ShipmentSerializer(shipment, context={"request": request}).data)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._workflow_response(lambda shipment: ShipmentWorkflowService.cancel(shipment, request.user, notes=request.data.get("notes")))

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        shipment = self.get_object()
        return Response(ShipmentEventSerializer(shipment.events.all(), many=True).data)

    @action(detail=False, methods=["get"])
    def incoming(self, request):
        office = get_current_office()
        company = get_current_company()
        qs = Shipment.objects.filter(is_active=True).select_related(
            "company",
            "origin_office",
            "destination_office",
            "from_city",
            "to_city",
            "consignor_city",
            "consignee_city",
            "created_by",
            "updated_by",
        )
        if company:
            qs = qs.filter(company=company)
        qs = qs.exclude(
            status__in=[Shipment.StatusChoices.DELIVERED, Shipment.StatusChoices.CANCELLED]
        )
        if office:
            latest_event = ShipmentEvent.unscoped_objects.filter(shipment=OuterRef("pk")).order_by("-occurred_at", "-created_at")
            qs = qs.annotate(
                latest_event_type=Subquery(latest_event.values("event_type")[:1]),
                latest_event_office_id=Subquery(latest_event.values("office_id")[:1]),
            ).filter(
                models.Q(destination_office=office)
                | models.Q(latest_event_type=ShipmentEvent.EventType.RECEIVED, latest_event_office_id=office.id)
            )
        elif not can_manage_company(request.user, company):
            qs = qs.none()
        filtered_qs = self.filter_queryset(qs)
        page = self.paginate_queryset(filtered_qs)
        if page is not None:
            return self.get_paginated_response(ShipmentListSerializer(page, many=True, context={"request": request}).data)
        return Response(ShipmentListSerializer(filtered_qs, many=True, context={"request": request}).data)

    def _workflow_response(self, callback):
        shipment = self.get_object()
        try:
            callback(shipment)
            return Response(ShipmentSerializer(shipment, context={"request": self.request}).data)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
