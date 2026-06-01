from django.urls import path, include
from core.views import (
    DocketMetadataView,
    MasterDataViewSet,
)
from dockets.views import DocketViewSet

master_list = MasterDataViewSet.as_view({
    'get': 'list',
    'post': 'create',
})
master_detail = MasterDataViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy',
})

docket_create = DocketViewSet.as_view({
    'post': 'create',
})

urlpatterns = [
    path('api/v1/auth/', include('authentication.urls')),
    path('api/v1/dockets/metadata/', DocketMetadataView.as_view(), name='docket-metadata'),
    path('api/v1/master/<str:resource>/', master_list, name='master-list'),
    path('api/v1/master/<str:resource>/<pk>/', master_detail, name='master-detail'),
    path('api/v1/new/', docket_create, name='docket-new'),
    path('api/v1/dockets/', include('dockets.urls')),
]
