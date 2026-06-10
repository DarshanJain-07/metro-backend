from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ExpenseViewSet, InvoiceViewSet, LedgerEntryViewSet, PaymentReceiptViewSet

router = DefaultRouter()
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'payments', PaymentReceiptViewSet, basename='payment')
router.register(r'ledger', LedgerEntryViewSet, basename='ledger')
router.register(r'expenses', ExpenseViewSet, basename='expense')

urlpatterns = [
    path('', include(router.urls)),
]
