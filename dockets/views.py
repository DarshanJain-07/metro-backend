from decimal import Decimal, ROUND_HALF_UP
from rest_framework import viewsets, status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Docket, RateCard, RateRule, BranchRatePolicy, DeliveryAssignment, DocketLineItem
from .serializers import (
    DocketListSerializer, DocketSerializer, 
    ProofOfDeliverySerializer, DeliveryAssignmentSerializer
)
from .filters import DocketFilter
from .permissions import StrictActionPermission, IsCompanyAdminPermission
from .admin_serializers import RateCardSerializer, RateRuleSerializer, BranchRatePolicySerializer
from .utils import generate_docket_no
from .services import DocketWorkflowService
from django_filters.rest_framework import DjangoFilterBackend
from core.request_context import get_current_company, get_current_branch
from core.viewsets import (
    IdempotentCreateMixin,
    OptimisticConcurrencyMixin,
    SoftDeleteMixin,
    TenantBranchScopedQuerysetMixin,
)

class RateCardViewSet(viewsets.ModelViewSet):
    queryset = RateCard.objects.all()
    serializer_class = RateCardSerializer
    permission_classes = [IsCompanyAdminPermission]

class RateRuleViewSet(viewsets.ModelViewSet):
    queryset = RateRule.objects.all()
    serializer_class = RateRuleSerializer
    permission_classes = [IsCompanyAdminPermission]

class BranchRatePolicyViewSet(viewsets.ModelViewSet):
    queryset = BranchRatePolicy.objects.all()
    serializer_class = BranchRatePolicySerializer
    permission_classes = [IsCompanyAdminPermission]

class DocketViewSet(
    IdempotentCreateMixin,
    OptimisticConcurrencyMixin,
    TenantBranchScopedQuerysetMixin,
    SoftDeleteMixin,
    viewsets.ModelViewSet,
):
    """
    ViewSet for viewing and editing Docket instances with strict permissions.
    """
    queryset = Docket.objects.none()
    serializer_class = DocketSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["docket_no", "consignor_name", "consignee_name", "consignor_city__name", "consignee_city__name"]
    ordering_fields = "__all__"
    ordering = ["-created_at"]
    filterset_class = DocketFilter
    permission_classes = [StrictActionPermission]
    branch_scope_permission = 'dockets.view_all_branches'

    def get_serializer_class(self):
        if self.action == 'list':
            return DocketListSerializer
        return DocketSerializer

    def get_queryset(self):
        # TenantManager handles company filtering from the DRF request context.
        qs = Docket.objects.filter(is_active=True).select_related(
            'company', 'origin_branch', 'destination_branch', 
            'from_city', 'to_city', 'consignor_city', 'consignee_city',
            'created_by', 'updated_by'
        )

        if self.action in ['retrieve', 'update', 'partial_update']:
            qs = qs.prefetch_related('line_items')
        
        return self.apply_branch_scope(qs)

    def perform_create(self, serializer):
        user = self.request.user
        date = serializer.validated_data.get('date')
        
        company = get_current_company()
        if not company:
            from rest_framework import serializers
            raise serializers.ValidationError({"company": "Active company context required."})

        docket_no = generate_docket_no(date, company)
        
        # Pass company explicitly since middleware might not run in tests
        serializer.save(company=company, docket_no=docket_no, **self.get_idempotency_save_kwargs())

    @action(detail=False, methods=['get'], url_path='suggested-rate')
    def suggested_rate(self, request):
        """
        Lookup the suggested rate based on origin, destination, and basis.
        """
        origin_branch_id = request.query_params.get('origin_branch')
        dest_branch_id = request.query_params.get('destination_branch')
        basis = request.query_params.get('basis')

        if not origin_branch_id or not dest_branch_id:
            return Response(
                {"detail": "origin_branch and destination_branch are required."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        from core.models import Branch
        try:
            origin_branch = Branch.objects.get(pk=origin_branch_id)
            dest_branch = Branch.objects.get(pk=dest_branch_id)
        except Branch.DoesNotExist:
            return Response({"detail": "Branch not found."}, status=status.HTTP_404_NOT_FOUND)

        company = get_current_company()
        rule = lookup_rate(company, origin_branch, dest_branch, basis)

        if not rule:
            return Response({"rate": None, "detail": "No rate rule found for this route."})

        return Response({
            "rate": float(rule.rate),
            "rate_type": rule.rate_type,
            "min_charge": float(rule.min_charge),
            "delivery_charge": float(rule.delivery_charge),
            "rule_id": rule.id
        })

    @action(detail=False, methods=['post'])
    def preview(self, request):
        """
        Calculate charges and totals without saving anything.
        """
        data = request.data
        line_items = data.get('line_items', [])
        additional_charges = Decimal(str(data.get('additional_charges', 0)))
        delivery_charge = Decimal(str(data.get('delivery_charge', 0)))
        advance_amount = Decimal(str(data.get('advance_amount', 0)))

        calculated_line_items = []
        total_freight = Decimal('0.00')
        total_pieces = 0
        total_actual_weight = Decimal('0.00')
        total_charged_weight = Decimal('0.00')

        for item in line_items:
            rate_type = item.get('rate_type', DocketLineItem.RateTypeChoices.PER_KG)
            pieces = int(item.get('pieces', 0))
            actual_weight = Decimal(str(item.get('actual_weight', 0)))
            charged_weight = Decimal(str(item.get('charged_weight', 0)))
            rate = Decimal(str(item.get('rate', 0)))
            
            charge = Decimal('0.00')
            if rate_type == DocketLineItem.RateTypeChoices.PER_PIECE:
                charge = (rate * pieces).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            elif rate_type == DocketLineItem.RateTypeChoices.PER_KG:
                charge = (rate * charged_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            elif rate_type == DocketLineItem.RateTypeChoices.FLAT:
                charge = rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            calculated_line_items.append({
                'id': item.get('id'),
                'charge': float(charge)
            })
            total_freight += charge
            total_pieces += pieces
            total_actual_weight += actual_weight
            total_charged_weight += charged_weight

        final_freight = total_freight + additional_charges + delivery_charge
        balance = final_freight - advance_amount

        return Response({
            'line_items': calculated_line_items,
            'freight': float(total_freight),
            'total_packages': total_pieces,
            'total_actual_weight': float(total_actual_weight),
            'total_charge_weight': float(total_charged_weight),
            'final_freight': float(final_freight),
            'remaining_balance': float(balance)
        })

    @action(detail=True, methods=['post'])
    def book(self, request, pk=None):
        docket = self.get_object()
        try:
            DocketWorkflowService.book_docket(docket, request.user)
            return Response(DocketSerializer(docket).data)
        except DjangoValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='mark-in-transit')
    def mark_in_transit(self, request, pk=None):
        docket = self.get_object()
        try:
            DocketWorkflowService.mark_in_transit(docket, request.user)
            return Response(DocketSerializer(docket).data)
        except DjangoValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        docket = self.get_object()
        try:
            DocketWorkflowService.receive_docket(docket, request.user)
            return Response(DocketSerializer(docket).data)
        except DjangoValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='assign-delivery')
    def assign_delivery(self, request, pk=None):
        docket = self.get_object()
        delivery_user_id = request.data.get('delivery_user')
        if not delivery_user_id:
            return Response({"detail": "delivery_user is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            delivery_user = User.objects.get(pk=delivery_user_id)
            assignment = DocketWorkflowService.assign_delivery(docket, delivery_user, request.user)
            return Response(DeliveryAssignmentSerializer(assignment).data)
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        except DjangoValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='mark-delivered')
    def mark_delivered(self, request, pk=None):
        docket = self.get_object()
        serializer = ProofOfDeliverySerializer(data=request.data)
        if serializer.is_valid():
            try:
                DocketWorkflowService.mark_delivered(docket, serializer.validated_data, request.user)
                return Response(DocketSerializer(docket).data)
            except DjangoValidationError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        docket = self.get_object()
        notes = request.data.get('notes')
        try:
            DocketWorkflowService.cancel_docket(docket, request.user, notes=notes)
            return Response(DocketSerializer(docket).data)
        except DjangoValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def incoming(self, request):
        """
        List dockets destined for the user's active branch.
        """
        user = request.user
        branch = get_current_branch()

        qs = self.get_queryset()
        
        from core.policies import has_role
        from core.models import Role
        
        # If user is not super admin or platform admin, they only see their destination branch incoming loads
        if not user.is_superuser and not has_role(user, roles=[Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN]):
            if branch:
                qs = qs.filter(destination_branch=branch)
            else:
                return Response({"detail": "Active branch context required."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Apply filters from DocketFilter
        filtered_qs = self.filter_queryset(qs)
        
        page = self.paginate_queryset(filtered_qs)
        if page is not None:
            serializer = DocketListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = DocketListSerializer(filtered_qs, many=True)
        return Response(serializer.data)
