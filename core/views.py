from django.db import IntegrityError, models, transaction
from django.db.models import Count, F, Sum
from django.http import Http404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.import_export_api import ImportExportViewSetMixin, dataset_from_rows
from core.import_export_resources import MASTER_IMPORT_EXPORT_RESOURCES
from core.models import City, CompanyOffice, GlobalOffice, MasterScope, OfficeStatus, Party, State
from core.policies import (
    active_office_ids,
    assign_master_scope,
    active_master_scope,
    can,
    can_manage_company,
    visible_master_scope_filter,
)
from core.request_context import get_current_company, get_current_office, get_current_role
from core.serializers import (
    CitySerializer,
    CompanyOfficeSerializer,
    GlobalOfficeSerializer,
    OfficeImportSerializer,
    OwnerCompanyOfficeImportSerializer,
    PartySerializer,
    StateSerializer,
)
from core.viewsets import IdempotentCreateMixin, OptimisticConcurrencyMixin, SoftDeleteMixin


def materialize_global_offices_from_company_offices():
    offices = CompanyOffice.unscoped_objects.filter(
        is_active=True,
        status=OfficeStatus.ACTIVE,
        global_office__isnull=True,
        scope_type=MasterScope.COMPANY,
    ).select_related("company", "city")

    for office in offices:
        global_office = GlobalOffice.unscoped_objects.filter(
            name__iexact=office.name,
            city=office.city,
        ).first()

        if not global_office:
            try:
                global_office = GlobalOffice.unscoped_objects.create(
                    name=office.name,
                    city=office.city,
                    owner_company=office.company,
                    address=office.address,
                    contact_name=office.contact_name,
                    phone=office.phone,
                    status=office.status,
                    is_active=office.is_active,
                )
            except IntegrityError:
                global_office = GlobalOffice.unscoped_objects.filter(
                    name__iexact=office.name,
                    city=office.city,
                ).first()

        if not global_office:
            continue

        update_fields = ["global_office", "updated_at"]
        if not global_office.owner_company_id:
            global_office.owner_company = office.company
            global_office.save(update_fields=["owner_company", "updated_at"])

        office.global_office = global_office
        office.save(update_fields=update_fields)


def company_scoped_queryset(queryset, user):
    if not user.is_authenticated:
        return queryset.none()
    if user.is_superuser:
        return queryset

    company = get_current_company()
    if not company:
        return queryset.none()

    qs = queryset.filter(company=company)
    if hasattr(queryset.model, "scope_type"):
        qs = qs.filter(visible_master_scope_filter(user, company))
    elif not can_manage_company(user, company):
        office_ids = active_office_ids(user, company)
        if hasattr(queryset.model, "office"):
            qs = qs.filter(models.Q(office__in=office_ids) | models.Q(office__isnull=True))
    return qs


class ActionModelPermission(BasePermission):
    action_permissions = {
        "list": "master:view",
        "retrieve": "master:view",
        "create": "master:create",
        "update": "master:edit",
        "partial_update": "master:edit",
        "destroy": "master:delete",
        "import_rows": "master:import",
        "import_file": "master:import",
        "export_file": "master:view",
        "import_office": "master:import",
        "import_company_offices": "master:import",
        "refresh_from_global": "master:edit",
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        action_name = getattr(view, "action", None)
        required_permission = self.action_permissions.get(action_name)
        if not required_permission:
            return False

        config = getattr(view, "_get_config", lambda: None)()
        if not config:
            return True
        if not config.get("company_scoped") and required_permission != "master:view":
            return False

        company = get_current_company()
        return can(request.user, required_permission, company=company, office=get_current_office(request.user))


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        company = get_current_company()
        if not company:
            return Response({"error": "No company context found"}, status=400)

        from accounts.models import Invoice, PaymentReceipt
        from shipments.models import Shipment

        shipments = Shipment.objects.filter(company=company)
        invoices = Invoice.objects.filter(company=company)
        payments = PaymentReceipt.objects.filter(company=company)

        office_id = request.query_params.get("office_id")
        if office_id:
            shipments = shipments.filter(
                models.Q(origin_office_id=office_id)
                | models.Q(destination_office_id=office_id)
                | models.Q(events__office_id=office_id)
            ).distinct()
            invoices = invoices.filter(office_id=office_id)
            payments = payments.filter(office_id=office_id)
        elif not can_manage_company(user, company):
            office_ids = active_office_ids(user, company)
            shipments = shipments.filter(
                models.Q(origin_office_id__in=office_ids)
                | models.Q(destination_office_id__in=office_ids)
                | models.Q(events__office_id__in=office_ids)
            ).distinct()
            invoices = invoices.filter(office_id__in=office_ids)
            payments = payments.filter(office_id__in=office_ids)

        stats = {
            "total_dockets": shipments.count(),
            "pending_deliveries": shipments.filter(status__in=["IN_TRANSIT", "RECEIVED"]).count(),
            "total_revenue": invoices.aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
            "total_receivables": (invoices.aggregate(Sum("total_amount"))["total_amount__sum"] or 0)
            - (invoices.aggregate(Sum("paid_amount"))["paid_amount__sum"] or 0),
            "recent_dockets": shipments.order_by("-created_at")[:5]
            .annotate(total_amount=F("final_freight"), docket_no=F("lr_no"))
            .values("docket_no", "status", "total_amount", "date"),
            "docket_status_distribution": list(shipments.values("status").annotate(count=Count("id"))),
        }
        return Response(stats)


class MasterDataViewSet(ImportExportViewSetMixin, IdempotentCreateMixin, OptimisticConcurrencyMixin, SoftDeleteMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, ActionModelPermission]
    filter_backends = [SearchFilter, OrderingFilter]
    ordering_fields = "__all__"
    ordering = ["id"]

    RESOURCE_CONFIG = {
        "states": {
            "model": State,
            "serializer_class": StateSerializer,
            "search_fields": ["name", "code"],
            "has_is_active": True,
            "company_scoped": False,
            "select_related": [],
        },
        "cities": {
            "model": City,
            "serializer_class": CitySerializer,
            "search_fields": ["name", "state__name", "state__code"],
            "has_is_active": True,
            "company_scoped": False,
            "select_related": ["state"],
        },
        "global-offices": {
            "model": GlobalOffice,
            "serializer_class": GlobalOfficeSerializer,
            "search_fields": ["name", "city__name", "phone"],
            "has_is_active": True,
            "company_scoped": False,
            "select_related": ["city", "city__state", "owner_company"],
        },
        "offices": {
            "model": CompanyOffice,
            "serializer_class": CompanyOfficeSerializer,
            "search_fields": ["name", "city__name", "phone", "address", "gst_number"],
            "has_is_active": True,
            "company_scoped": True,
            "select_related": ["company", "city", "city__state", "global_office", "global_office__owner_company"],
        },
        "parties": {
            "model": Party,
            "serializer_class": PartySerializer,
            "search_fields": ["name", "phone", "address", "city__name", "gst_number"],
            "has_is_active": True,
            "company_scoped": True,
            "select_related": ["city", "city__state"],
        },
    }

    def _get_config(self):
        resource = self.kwargs.get("resource")
        if resource not in self.RESOURCE_CONFIG:
            raise Http404("Resource not found")
        return self.RESOURCE_CONFIG[resource]

    def get_import_export_resource_class(self):
        resource = self.kwargs.get("resource")
        try:
            return MASTER_IMPORT_EXPORT_RESOURCES[resource]
        except KeyError:
            raise Http404("Resource not found")

    @property
    def search_fields(self):
        return self._get_config()["search_fields"]

    def get_serializer_class(self):
        return self._get_config()["serializer_class"]

    def get_queryset(self):
        config = self._get_config()
        if self.kwargs.get("resource") == "global-offices":
            materialize_global_offices_from_company_offices()

        model = config["model"]
        qs = model.unscoped_objects.all() if hasattr(model, "unscoped_objects") else model.objects.all()
        if config["select_related"]:
            qs = qs.select_related(*config["select_related"])
        if config["company_scoped"]:
            qs = company_scoped_queryset(qs, self.request.user)
        if config["has_is_active"]:
            include_inactive = self.request.query_params.get("include_inactive", "true") == "true"
            if not include_inactive:
                qs = qs.filter(is_active=True)
        if self.kwargs.get("resource") == "offices":
            own_company_only = self.request.query_params.get("own_company_only", "false") == "true"
            company = get_current_company()
            if own_company_only:
                qs = qs.filter(
                    models.Q(global_office__isnull=True)
                    | models.Q(global_office__owner_company__isnull=True)
                    | models.Q(global_office__owner_company=company)
                )
            if "ordering" not in self.request.query_params:
                qs = qs.order_by("global_office__owner_company__name", "name")
        return qs

    def perform_create(self, serializer):
        config = self._get_config()
        save_kwargs = self.get_idempotency_save_kwargs()
        if config["company_scoped"]:
            company = get_current_company()
            if not company:
                raise serializers.ValidationError({"detail": "Active company context required."})
            if hasattr(config["model"], "scope_type"):
                scope_type, scope_id = active_master_scope(
                    role=get_current_role(),
                    office=get_current_office(self.request.user),
                )
                save_kwargs.update({"scope_type": scope_type, "scope_id": scope_id})
            serializer.save(company=company, **save_kwargs)
        else:
            serializer.save(**save_kwargs)

    @action(detail=False, methods=["post"], url_path="import-rows")
    def import_rows(self, request, resource=None):
        config = self._get_config()
        rows = request.data.get("rows") if isinstance(request.data, dict) else request.data
        if not isinstance(rows, list):
            raise serializers.ValidationError({"rows": "Expected a list of records."})
        if not rows:
            raise serializers.ValidationError({"rows": "At least one record is required."})
        if config["company_scoped"] and not get_current_company():
            raise serializers.ValidationError({"detail": "Active company context required."})
        return self.run_dataset_import(dataset_from_rows(rows))

    @action(detail=False, methods=["post"], url_path="import")
    def import_office(self, request, resource=None):
        if resource != "offices":
            raise Http404("Resource not found")
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"detail": "Active company context required."})
        serializer = OfficeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        global_office = serializer.validated_data["global_office"]
        office = CompanyOffice.copy_from_global(
            company,
            global_office,
            office_type=serializer.validated_data.get("office_type"),
        )
        assign_master_scope(office, role=get_current_role(), office=get_current_office(request.user))
        office.save()
        return Response(CompanyOfficeSerializer(office).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="import-company-offices")
    def import_company_offices(self, request, resource=None):
        if resource != "offices":
            raise Http404("Resource not found")
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"detail": "Active company context required."})
        serializer = OwnerCompanyOfficeImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offices = GlobalOffice.objects.filter(
            owner_company_id=serializer.validated_data["owner_company"],
            status=OfficeStatus.ACTIVE,
        )
        created = []
        for global_office in offices:
            if CompanyOffice.unscoped_objects.filter(company=company, global_office=global_office).exists():
                continue
            office = CompanyOffice.copy_from_global(
                company,
                global_office,
                office_type=serializer.validated_data.get("office_type"),
            )
            assign_master_scope(office, role=get_current_role(), office=get_current_office(request.user))
            office.save()
            created.append(office)
        return Response(CompanyOfficeSerializer(created, many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="refresh-from-global")
    def refresh_from_global(self, request, pk=None, resource=None):
        if resource != "offices":
            raise Http404("Resource not found")
        office = self.get_object()
        if not office.global_office_id:
            return Response({"detail": "Office is not linked to a global office."}, status=status.HTTP_400_BAD_REQUEST)
        office.refresh_from_global()
        return Response(CompanyOfficeSerializer(office).data)


class ShipmentMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        company = get_current_company()
        if not company:
            return Response({"error": "No company context found"}, status=400)
        office = get_current_office(user)

        from django.core.cache import cache

        office_cache_id = office.id if office else "none"
        cache_key = f"shipment_metadata_{company.id}_{office_cache_id}_{user.id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        offices = company_scoped_queryset(
            CompanyOffice.objects.select_related("city", "city__state").order_by("name"),
            user,
        ).filter(is_active=True, status=OfficeStatus.ACTIVE)
        cities = City.objects.filter(is_active=True).select_related("state").order_by("id")
        states = State.objects.order_by("id")
        parties = company_scoped_queryset(
            Party.objects.select_related("city", "city__state").order_by("name"),
            user,
        ).filter(is_active=True)

        data = {
            "branches": CompanyOfficeSerializer(offices, many=True).data,
            "cities": CitySerializer(cities, many=True).data,
            "states": StateSerializer(states, many=True).data,
            "parties": PartySerializer(parties, many=True).data,
            "user_branch": office.id if office else None,
        }
        cache.set(cache_key, data, 300)  # Cache for 5 minutes
        return Response(data)
