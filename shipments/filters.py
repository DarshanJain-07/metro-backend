import django_filters
from django.db.models import Q

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
    status = django_filters.ChoiceFilter(choices=Shipment.StatusChoices.choices)

    class Meta:
        model = Shipment
        fields = []

    def filter_by_party_name(self, queryset, name, value):
        return queryset.filter(Q(consignor_name__icontains=value) | Q(consignee_name__icontains=value))
