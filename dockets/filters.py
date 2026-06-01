import django_filters
from .models import Docket
from django.db.models import Q

class DocketFilter(django_filters.FilterSet):
    # Search Filters
    docket_no = django_filters.CharFilter(lookup_expr='icontains')
    consignor_name = django_filters.CharFilter(lookup_expr='icontains')
    consignee_name = django_filters.CharFilter(lookup_expr='icontains')
    
    # Date Range Filters
    from_date = django_filters.DateFilter(field_name="date", lookup_expr='gte')
    to_date = django_filters.DateFilter(field_name="date", lookup_expr='lte')
    
    # Exact Branch Filters
    origin_branch = django_filters.NumberFilter(field_name="origin_branch", lookup_expr='exact')
    destination_branch = django_filters.NumberFilter(field_name="destination_branch", lookup_expr='exact')
    origin_branch_name = django_filters.CharFilter(field_name="origin_branch__name", lookup_expr='icontains')
    destination_branch_name = django_filters.CharFilter(field_name="destination_branch__name", lookup_expr='icontains')
    
    # Single search for either Consignor OR Consignee
    party_name = django_filters.CharFilter(method='filter_by_party_name', label="Search by Party Name (Consignor/Consignee)")

    class Meta:
        model = Docket
        fields = []

    def filter_by_party_name(self, queryset, name, value):
        # This searches both fields for the provided string
        return queryset.filter(
            Q(consignor_name__icontains=value) | Q(consignee_name__icontains=value)
        )
