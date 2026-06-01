from django.urls import path
from .views import DocketViewSet

docket_list = DocketViewSet.as_view({
    'get': 'list',
})

docket_detail = DocketViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy',
})

urlpatterns = [
    path('', docket_list, name='docket-list'),
    path('<pk>/', docket_detail, name='docket-detail'),
]
