from rest_framework import serializers, viewsets, status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import Http404
from django.db import models
from django.db.models import Sum, Count, F

from .models import Branch, City, Party, State
from .serializers import BranchSerializer, CitySerializer, PartySerializer, StateSerializer
from .viewsets import (
    OptimisticConcurrencyMixin, 
    SoftDeleteMixin, 
    IdempotentCreateMixin
)


from core.policies import has_role, can_manage_company
from core.models import Role
from core.request_context import get_current_company, get_current_branch


def company_scoped_queryset(queryset, user):
    if not user.is_authenticated:
        return queryset.none()
    if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
        return queryset
        
    company = get_current_company()
    if not company:
        return queryset.none()
        
    qs = queryset.filter(company=company)
    
    if not has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN]):
        active_branches = list(user.memberships.filter(is_active=True).values_list('branch', flat=True))
        if hasattr(queryset.model, 'branch'):
            qs = qs.filter(models.Q(branch__in=active_branches) | models.Q(branch__isnull=True))
    return qs


class ActionModelPermission(BasePermission):
    """
    Require standard policy checks for mutating viewset actions.
    List and retrieve still require authentication through IsAuthenticated.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
            
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        action = getattr(view, 'action', None)
        if action in ['list', 'retrieve']:
            return True

        config = getattr(view, '_get_config', lambda: None)()
        if not config:
            return True

        # If not company scoped (like State, City), only Platform Admin can mutate
        if not config.get('company_scoped'):
            return False 

        company = get_current_company() or getattr(request.user, 'company', None)
        if company and can_manage_company(request.user, company):
            return True

        return False


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        company = get_current_company()
        if not company:
            return Response({"error": "No company context found"}, status=400)

        # To avoid circular imports
        from dockets.models import Docket
        from accounts.models import Invoice, PaymentReceipt

        # Filter dockets by company
        dockets = Docket.objects.filter(company=company)
        invoices = Invoice.objects.filter(company=company)
        payments = PaymentReceipt.objects.filter(company=company)

        # If branch admin or below, further filter by branch
        branch_id = request.query_params.get('branch_id')
        if branch_id:
            dockets = dockets.filter(models.Q(origin_branch_id=branch_id) | models.Q(destination_branch_id=branch_id))
            invoices = invoices.filter(branch_id=branch_id)
            payments = payments.filter(branch_id=branch_id)
        elif not has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN, Role.PLATFORM_ADMIN]):
            active_branches = list(user.memberships.filter(is_active=True).values_list('branch', flat=True))
            dockets = dockets.filter(models.Q(origin_branch_id__in=active_branches) | models.Q(destination_branch_id__in=active_branches))
            invoices = invoices.filter(branch_id__in=active_branches)
            payments = payments.filter(branch_id__in=active_branches)

        stats = {
            "total_dockets": dockets.count(),
            "pending_deliveries": dockets.filter(status='IN_TRANSIT').count(),
            "total_revenue": invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            "total_receivables": (invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0) - (invoices.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0),
            "recent_dockets": dockets.order_by('-created_at')[:5].annotate(total_amount=F('final_freight')).values('docket_no', 'status', 'total_amount', 'date'),
            "docket_status_distribution": list(dockets.values('status').annotate(count=Count('id')))
        }

        return Response(stats)


class MasterDataViewSet(
    IdempotentCreateMixin,
    OptimisticConcurrencyMixin,
    SoftDeleteMixin,
    viewsets.ModelViewSet
):
    permission_classes = [IsAuthenticated, ActionModelPermission]
    filter_backends = [SearchFilter, OrderingFilter]
    ordering_fields = '__all__'
    ordering = ['id']

    RESOURCE_CONFIG = {
        'states': {
            'model': State,
            'serializer_class': StateSerializer,
            'search_fields': ['name', 'code'],
            'has_is_active': True,
            'company_scoped': False,
            'select_related': [],
        },
        'cities': {
            'model': City,
            'serializer_class': CitySerializer,
            'search_fields': ['name', 'state__name', 'state__code'],
            'has_is_active': True,
            'company_scoped': False,
            'select_related': ['state'],
        },
        'branches': {
            'model': Branch,
            'serializer_class': BranchSerializer,
            'search_fields': ['name', 'city__name', 'city__state__code'],
            'has_is_active': True,
            'company_scoped': True,
            'select_related': ['city', 'city__state'],
        },
        'parties': {
            'model': Party,
            'serializer_class': PartySerializer,
            'search_fields': ['name', 'phone', 'city__name', 'gst_number'],
            'has_is_active': True,
            'company_scoped': True,
            'select_related': ['city', 'city__state'],
        }
    }

    def _get_config(self):
        resource = self.kwargs.get('resource')
        if resource not in self.RESOURCE_CONFIG:
            raise Http404("Resource not found")
        return self.RESOURCE_CONFIG[resource]

    @property
    def search_fields(self):
        return self._get_config()['search_fields']

    def get_serializer_class(self):
        return self._get_config()['serializer_class']

    def get_queryset(self):
        config = self._get_config()
        model = config['model']
        
        # Use unscoped_objects if available to avoid double filtering with TenantManager
        if hasattr(model, 'unscoped_objects'):
            qs = model.unscoped_objects.all()
        else:
            qs = model.objects.all()

        if config['select_related']:
            qs = qs.select_related(*config['select_related'])

        if config['company_scoped']:
            qs = company_scoped_queryset(qs, self.request.user)

        if config['has_is_active']:
            # For master data, we want to display everything by default
            include_inactive = self.request.query_params.get('include_inactive', 'true') == 'true'
            if not include_inactive:
                qs = qs.filter(is_active=True)

        return qs

    def perform_create(self, serializer):
        config = self._get_config()
        save_kwargs = self.get_idempotency_save_kwargs()
        
        if config['company_scoped']:
            company = getattr(self.request.user, 'company', None)
            if not company:
                raise serializers.ValidationError({
                    "detail": "User must be assigned to a company before creating this resource."
                })
            serializer.save(company=company, **save_kwargs)
        else:
            serializer.save(**save_kwargs)

    def perform_update(self, serializer):
        # OptimisticConcurrencyMixin.perform_update handles check_precondition
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        config = self._get_config()
        if config['has_is_active']:
            # Use the SoftDeleteMixin logic through super or directly
            super().perform_destroy(instance)
        else:
            instance.delete()


class DocketMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        branches = company_scoped_queryset(
            Branch.objects.select_related('city', 'city__state').order_by('id'),
            user,
        ).filter(is_active=True)
        cities = City.objects.filter(is_active=True).select_related('state').order_by('id')
        states = State.objects.order_by('id')

        branch = get_current_branch(user)
        return Response({
            'branches': BranchSerializer(branches, many=True).data,
            'cities': CitySerializer(cities, many=True).data,
            'states': StateSerializer(states, many=True).data,
            'parties': [],
            'user_branch': branch.id if branch else None,
        })
