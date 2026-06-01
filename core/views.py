from django.http import Http404
from rest_framework import serializers, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Branch, City, Party, State
from .serializers import BranchSerializer, CitySerializer, PartySerializer, StateSerializer


def user_can_see_all_companies(user):
    return bool(getattr(user, 'is_superuser', False) or getattr(user, 'is_owner', False))


def company_scoped_queryset(queryset, user):
    if getattr(user, 'company_id', None):
        return queryset.filter(company=user.company)
    if user_can_see_all_companies(user):
        return queryset
    return queryset.none()


class ActionModelPermission(BasePermission):
    """
    Require standard Django model permissions for mutating viewset actions.
    List and retrieve still require authentication through IsAuthenticated.
    """

    permission_map = {
        'create': 'add',
        'update': 'change',
        'partial_update': 'change',
        'destroy': 'delete',
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or getattr(request.user, 'is_owner', False):
            return True

        perm_action = self.permission_map.get(getattr(view, 'action', None))
        if not perm_action:
            return True

        queryset = view.get_queryset()
        model = queryset.model
        return request.user.has_perm(f'{model._meta.app_label}.{perm_action}_{model._meta.model_name}')


class MasterDataViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ActionModelPermission]
    filter_backends = [SearchFilter]

    RESOURCE_CONFIG = {
        'states': {
            'model': State,
            'serializer_class': StateSerializer,
            'search_fields': ['name', 'code'],
            'order_by': 'name',
            'has_is_active': False,
            'company_scoped': False,
            'select_related': [],
        },
        'cities': {
            'model': City,
            'serializer_class': CitySerializer,
            'search_fields': ['name', 'state__name', 'state__code'],
            'order_by': 'name',
            'has_is_active': True,
            'company_scoped': False,
            'select_related': ['state'],
        },
        'branches': {
            'model': Branch,
            'serializer_class': BranchSerializer,
            'search_fields': ['name', 'city__name', 'city__state__code'],
            'order_by': 'name',
            'has_is_active': True,
            'company_scoped': True,
            'select_related': ['city', 'city__state'],
        },
        'parties': {
            'model': Party,
            'serializer_class': PartySerializer,
            'search_fields': ['name', 'phone', 'city__name', 'gst_number'],
            'order_by': 'name',
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
        qs = model.objects.all()

        if config['select_related']:
            qs = qs.select_related(*config['select_related'])

        qs = qs.order_by(config['order_by'])

        if config['company_scoped']:
            qs = company_scoped_queryset(qs, self.request.user)

        if config['has_is_active']:
            include_inactive = self.request.query_params.get('include_inactive') == 'true'
            if not include_inactive:
                qs = qs.filter(is_active=True)

        return qs

    def perform_create(self, serializer):
        config = self._get_config()
        if config['company_scoped']:
            if not getattr(self.request.user, 'company_id', None):
                raise serializers.ValidationError("User must be assigned to a company before creating this resource.")
            serializer.save(company=self.request.user.company)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        config = self._get_config()
        if config['has_is_active']:
            instance.is_active = False
            instance.save(update_fields=['is_active'])
        else:
            instance.delete()


class DocketMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        branches = company_scoped_queryset(
            Branch.objects.select_related('city', 'city__state').order_by('name'),
            user,
        ).filter(is_active=True)
        cities = City.objects.filter(is_active=True).select_related('state').order_by('name')
        states = State.objects.order_by('name')

        return Response({
            'branches': BranchSerializer(branches, many=True).data,
            'cities': CitySerializer(cities, many=True).data,
            'states': StateSerializer(states, many=True).data,
            'parties': [],
            'user_branch': user.branch_id,
        })
