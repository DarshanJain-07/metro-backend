import django_filters
from django.db.models import Q

from core.models import Party
from core.request_context import get_current_company
from .models import Shipment


class ShipmentFilter(django_filters.FilterSet):
    lr_no = django_filters.CharFilter(lookup_expr="icontains")
    consignor_name = django_filters.CharFilter(lookup_expr="icontains")
    consignee_name = django_filters.CharFilter(lookup_expr="icontains")
    from_date = django_filters.DateFilter(field_name="date", lookup_expr="gte", input_formats=["%d/%m/%Y", "%Y-%m-%d"])
    to_date = django_filters.DateFilter(field_name="date", lookup_expr="lte", input_formats=["%d/%m/%Y", "%Y-%m-%d"])
    origin_office = django_filters.CharFilter(field_name="origin_office", lookup_expr="exact")
    destination_office = django_filters.CharFilter(field_name="destination_office", lookup_expr="exact")
    origin_office_name = django_filters.CharFilter(field_name="origin_office__name", lookup_expr="icontains")
    destination_office_name = django_filters.CharFilter(field_name="destination_office__name", lookup_expr="icontains")
    party_name = django_filters.CharFilter(method="filter_by_party_name")
    party = django_filters.CharFilter(method="filter_by_party")
    basis = django_filters.ChoiceFilter(choices=Shipment.BasisChoices.choices)
    payment_type = django_filters.ChoiceFilter(choices=Shipment.PaymentTypeChoices.choices)
    status = django_filters.ChoiceFilter(choices=Shipment.StatusChoices.choices)
    is_billed = django_filters.BooleanFilter(method="filter_by_billed")
    exclude_paid = django_filters.BooleanFilter(method="filter_exclude_paid")

    class Meta:
        model = Shipment
        fields = []

    def filter_by_party_name(self, queryset, name, value):
        return queryset.filter(Q(consignor_name__icontains=value) | Q(consignee_name__icontains=value))

    def filter_by_party(self, queryset, name, value):
        company = get_current_company()
        party = Party.objects.filter(id=value, company=company).first()
        if not party:
            return queryset.none()
        return queryset.filter(Q(consignor_name=party.name) | Q(consignee_name=party.name))

    def filter_by_billed(self, queryset, name, value):
        lookup = {"invoice_lines__isnull": not value}
        return queryset.filter(**lookup)

    def filter_exclude_paid(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.exclude(basis=Shipment.BasisChoices.PAID)
