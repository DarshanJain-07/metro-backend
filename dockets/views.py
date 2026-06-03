from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Docket, RateCard, RateRule, BranchRatePolicy, DeliveryAssignment
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
    filter_backends = [DjangoFilterBackend]
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
        
        # Pass the current company to the generator (still needed for prefixing)
        company = get_current_company(user)

        docket_no = generate_docket_no(date, company)
        
        # Pass company explicitly since middleware might not run in tests
        serializer.save(company=company, docket_no=docket_no, **self.get_idempotency_save_kwargs())

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
        # Get active branch from context or membership
        branch = get_current_branch(user)
        
        if not branch:
             # Try to infer if only one active branch
             active_branches = user.memberships.filter(is_active=True).values_list('branch', flat=True)
             if len(active_branches) == 1:
                 from core.models import Branch
                 branch = Branch.objects.get(pk=active_branches[0])

        qs = self.get_queryset()
        
        from core.policies import has_role
        from core.models import Role
        
        # If user is not super admin or platform admin, they only see their destination branch incoming loads
        if not user.is_superuser and not has_role(user, roles=[Role.PLATFORM_ADMIN, Role.CLIENT_SUPER_ADMIN]):
            if branch:
                qs = qs.filter(destination_branch=branch)
            else:
                return Response({"detail": "Active branch not found for user."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Apply filters from DocketFilter
        filtered_qs = self.filter_queryset(qs)
        
        page = self.paginate_queryset(filtered_qs)
        if page is not None:
            serializer = DocketListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = DocketListSerializer(filtered_qs, many=True)
        return Response(serializer.data)

