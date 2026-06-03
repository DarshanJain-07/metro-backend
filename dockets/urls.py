from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import DocketViewSet, RateCardViewSet, RateRuleViewSet, BranchRatePolicyViewSet

router = DefaultRouter()
router.register(r'rate-cards', RateCardViewSet, basename='rate-card')
router.register(r'rate-rules', RateRuleViewSet, basename='rate-rule')
router.register(r'branch-rate-policies', BranchRatePolicyViewSet, basename='branch-rate-policy')
router.register(r'', DocketViewSet, basename='docket')

urlpatterns = [
    path('', include(router.urls)),
]
