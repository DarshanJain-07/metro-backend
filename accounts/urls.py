from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import InvoiceViewSet, PaymentReceiptViewSet, LedgerEntryViewSet

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'payments', PaymentReceiptViewSet, basename='payment')
router.register(r'ledger', LedgerEntryViewSet, basename='ledger')

urlpatterns = [
    path('', include(router.urls)),
]
