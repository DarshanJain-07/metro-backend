from django.db import IntegrityError, models, transaction
from django.db.models import Count, F, Sum
from django.http import Http404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import City, CompanyOffice, GlobalOffice, OfficeStatus, Party, Role, State
from core.policies import active_office_ids, can_manage_company, has_role
from core.request_context import get_current_company, get_current_office
from core.serializers import (
    BulkOfficeImportSerializer,
    CitySerializer,
    CompanyOfficeSerializer,
    GlobalOfficeSerializer,
    OfficeImportSerializer,
    PartySerializer,
    StateSerializer,
)
from core.viewsets import IdempotentCreateMixin, OptimisticConcurrencyMixin, SoftDeleteMixin


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
        office_ids = active_office_ids(user, company)
        if hasattr(queryset.model, "office"):
            qs = qs.filter(models.Q(office__in=office_ids) | models.Q(office__isnull=True))
    return qs


class ActionModelPermission(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser or has_role(request.user, roles=[Role.PLATFORM_ADMIN]):
            return True

        action_name = getattr(view, "action", None)
        if action_name in ["list", "retrieve"]:
            return True

        config = getattr(view, "_get_config", lambda: None)()
        if not config:
            return True
        if not config.get("company_scoped"):
            return False

        company = get_current_company()
        return bool(company and can_manage_company(request.user, company))


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
        elif not has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN, Role.PLATFORM_ADMIN]):
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


class MasterDataViewSet(IdempotentCreateMixin, OptimisticConcurrencyMixin, SoftDeleteMixin, viewsets.ModelViewSet):
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
            "search_fields": ["name", "city__name", "phone"],
            "has_is_active": True,
            "company_scoped": True,
            "select_related": ["city", "city__state", "global_office"],
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

    @property
    def search_fields(self):
        return self._get_config()["search_fields"]

    def get_serializer_class(self):
        return self._get_config()["serializer_class"]

    def get_queryset(self):
        config = self._get_config()
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
        return qs

    def perform_create(self, serializer):
        config = self._get_config()
        save_kwargs = self.get_idempotency_save_kwargs()
        if config["company_scoped"]:
            company = get_current_company()
            if not company:
                raise serializers.ValidationError({"detail": "Active company context required."})
            serializer.save(company=company, **save_kwargs)
        else:
            serializer.save(**save_kwargs)

    @action(detail=False, methods=["post"], url_path="bulk-create")
    def bulk_create(self, request, resource=None):
        config = self._get_config()
        rows = request.data.get("rows") if isinstance(request.data, dict) else request.data
        if not isinstance(rows, list):
            raise serializers.ValidationError({"rows": "Expected a list of records."})
        if not rows:
            raise serializers.ValidationError({"rows": "At least one record is required."})

        row_serializers = []
        row_errors = []
        for index, row in enumerate(rows, start=1):
            serializer = self.get_serializer(data=row)
            if serializer.is_valid():
                row_serializers.append((index, serializer))
            else:
                row_errors.append({"row": index, "errors": serializer.errors})

        if row_errors:
            return Response({"errors": row_errors}, status=status.HTTP_400_BAD_REQUEST)

        save_kwargs = {}
        if config["company_scoped"]:
            company = get_current_company()
            if not company:
                raise serializers.ValidationError({"detail": "Active company context required."})
            save_kwargs["company"] = company

        instances = []
        try:
            with transaction.atomic():
                for index, serializer in row_serializers:
                    try:
                        instances.append(serializer.save(**save_kwargs))
                    except IntegrityError:
                        raise serializers.ValidationError(
                            {
                                "errors": [
                                    {
                                        "row": index,
                                        "errors": [
                                            "Could not save this row because it conflicts with existing data."
                                        ],
                                    }
                                ]
                            }
                        )
        except serializers.ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        return Response(self.get_serializer(instances, many=True).data, status=status.HTTP_201_CREATED)

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
        office.save()
        return Response(CompanyOfficeSerializer(office).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="bulk-import")
    def bulk_import_offices(self, request, resource=None):
        if resource != "offices":
            raise Http404("Resource not found")
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"detail": "Active company context required."})
        serializer = BulkOfficeImportSerializer(data=request.data)
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
        office = get_current_office(user)
        return Response(
            {
                "branches": CompanyOfficeSerializer(offices, many=True).data,
                "cities": CitySerializer(cities, many=True).data,
                "states": StateSerializer(states, many=True).data,
                "parties": PartySerializer(parties, many=True).data,
                "user_branch": office.id if office else None,
            }
        )
