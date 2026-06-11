from django.urls import include, path

from core.views import DashboardStatsView, MasterDataViewSet, ShipmentMetadataView

master_list = MasterDataViewSet.as_view({"get": "list", "post": "create"})
master_detail = MasterDataViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"})
master_import = MasterDataViewSet.as_view({"post": "import_office"})
master_bulk_import = MasterDataViewSet.as_view({"post": "bulk_import_offices"})
master_bulk_create = MasterDataViewSet.as_view({"post": "bulk_create"})
master_refresh = MasterDataViewSet.as_view({"post": "refresh_from_global"})

urlpatterns = [
    path("api/v1/auth/", include("authentication.urls")),
    path("api/v1/shipments/metadata/", ShipmentMetadataView.as_view(), name="shipment-metadata"),
    path("api/v1/dashboard/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("api/v1/master/<str:resource>/", master_list, name="master-list"),
    path("api/v1/master/<str:resource>/import/", master_import, name="master-import"),
    path("api/v1/master/<str:resource>/bulk-import/", master_bulk_import, name="master-bulk-import"),
    path("api/v1/master/<str:resource>/bulk-create/", master_bulk_create, name="master-bulk-create"),
    path("api/v1/master/<str:resource>/<pk>/refresh-from-global/", master_refresh, name="master-refresh-global"),
    path("api/v1/master/<str:resource>/<pk>/", master_detail, name="master-detail"),
    path("api/v1/shipments/", include("shipments.urls")),
    path("api/v1/accounts/", include("accounts.urls")),
]
