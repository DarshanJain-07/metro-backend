from django.urls import include, path

from core.views import DashboardStatsView, MasterDataViewSet, ShipmentMetadataView

master_list = MasterDataViewSet.as_view({"get": "list", "post": "create"})
master_detail = MasterDataViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"})
master_import = MasterDataViewSet.as_view({"post": "import_office"})
master_import_company_offices = MasterDataViewSet.as_view({"post": "import_company_offices"})
master_import_rows = MasterDataViewSet.as_view({"post": "import_rows"})
master_refresh = MasterDataViewSet.as_view({"post": "refresh_from_global"})

urlpatterns = [
    path("api/v1/auth/", include("authentication.urls")),
    path("api/v1/shipments/metadata/", ShipmentMetadataView.as_view(), name="shipment-metadata"),
    path("api/v1/dashboard/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("api/v1/master/<str:resource>/", master_list, name="master-list"),
    path("api/v1/master/<str:resource>/import/", master_import, name="master-import"),
    path("api/v1/master/<str:resource>/import-company-offices/", master_import_company_offices, name="master-import-company-offices"),
    path("api/v1/master/<str:resource>/import-rows/", master_import_rows, name="master-import-rows"),
    path("api/v1/master/<str:resource>/<pk>/refresh-from-global/", master_refresh, name="master-refresh-global"),
    path("api/v1/master/<str:resource>/<pk>/", master_detail, name="master-detail"),
    path("api/v1/shipments/", include("shipments.urls")),
    path("api/v1/accounts/", include("accounts.urls")),
]
