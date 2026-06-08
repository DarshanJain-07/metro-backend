from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import OfficeRatePolicyViewSet, RateCardViewSet, RateRuleViewSet, ShipmentViewSet

router = DefaultRouter()
router.register(r"rate-cards", RateCardViewSet, basename="rate-card")
router.register(r"rate-rules", RateRuleViewSet, basename="rate-rule")
router.register(r"office-rate-policies", OfficeRatePolicyViewSet, basename="office-rate-policy")
router.register(r"", ShipmentViewSet, basename="shipment")

urlpatterns = [
    path("", include(router.urls)),
]
