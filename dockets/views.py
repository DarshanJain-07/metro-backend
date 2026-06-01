from rest_framework import viewsets
from .models import Docket
from .serializers import DocketListSerializer, DocketSerializer
from .filters import DocketFilter
from .permissions import StrictActionPermission
from .utils import generate_docket_no
from django_filters.rest_framework import DjangoFilterBackend
from core.viewsets import (
    IdempotentCreateMixin,
    OptimisticConcurrencyMixin,
    SoftDeleteMixin,
    TenantBranchScopedQuerysetMixin,
)


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
        
        # Pass the user's company to the generator (still needed for prefixing)
        docket_no = generate_docket_no(date, user.company)
        
        # AuditBaseModel handles company, created_by, updated_by automatically
        serializer.save(docket_no=docket_no, **self.get_idempotency_save_kwargs())
