from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
import uuid

from core.models import User, Company, Branch, City, State, Role, UserMembership, Party
from dockets.models import Docket
from .models import Invoice, PaymentReceipt, LedgerEntry, BankPaymentVerification

class AccountsAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        self.company = Company.objects.create(name="Metro Logistics")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.branch = Branch.objects.create(company=self.company, name="Mumbai Branch", city=self.city)
        self.party = Party.objects.create(
            company=self.company, name="Test Party", phone="9876543210", address="Test Address", city=self.city
        )

        # Users
        self.accountant = User.objects.create_user(username="accountant", password="password", company=self.company)
        UserMembership.objects.create(user=self.accountant, company=self.company, branch=self.branch, role=Role.ACCOUNTANT)

        self.booking_user = User.objects.create_user(username="booking", password="password", company=self.company)
        UserMembership.objects.create(user=self.booking_user, company=self.company, branch=self.branch, role=Role.BOOKING_USER)

        # Dockets
        self.docket_tbb = Docket.objects.create(
            company=self.company, docket_no="DOC001", date=timezone.now().date(),
            from_city=self.city, origin_branch=self.branch,
            to_city=self.city, destination_branch=self.branch,
            consignor_name="C1", consignor_city=self.city, consignor_phone="9999999999", consignor_address="Add1",
            consignee_name="C2", consignee_city=self.city, consignee_phone="8888888888", consignee_address="Add2",
            payment_type=Docket.PaymentTypeChoices.TBB,
            freight=1000, additional_charges=0, delivery_charge=0,
            total_actual_weight=100, total_charge_weight=100, total_packages=10,
            created_by=self.booking_user
        )

        self.docket_paid = Docket.objects.create(
            company=self.company, docket_no="DOC002", date=timezone.now().date(),
            from_city=self.city, origin_branch=self.branch,
            to_city=self.city, destination_branch=self.branch,
            consignor_name="C1", consignor_city=self.city, consignor_phone="9999999999", consignor_address="Add1",
            consignee_name="C2", consignee_city=self.city, consignee_phone="8888888888", consignee_address="Add2",
            payment_type=Docket.PaymentTypeChoices.PAID,
            freight=500, additional_charges=0, delivery_charge=0,
            total_actual_weight=50, total_charge_weight=50, total_packages=5,
            created_by=self.booking_user
        )

    def test_generate_invoice_tbb(self):
        self.client.force_authenticate(user=self.accountant)
        url = reverse('invoice-generate')
        data = {
            "party": self.party.id,
            "branch": self.branch.id,
            "dockets": [self.docket_tbb.id],
            "due_date": (timezone.now().date() + timedelta(days=15)).strftime("%Y-%m-%d")
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify Ledger Entry
        self.assertTrue(LedgerEntry.objects.filter(
            company=self.company, party=self.party, entry_type=LedgerEntry.EntryType.DEBIT
        ).exists())

    def test_generate_invoice_paid_fails(self):
        self.client.force_authenticate(user=self.accountant)
        url = reverse('invoice-generate')
        data = {
            "party": self.party.id,
            "branch": self.branch.id,
            "dockets": [self.docket_paid.id],
            "due_date": (timezone.now().date() + timedelta(days=15)).strftime("%Y-%m-%d")
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is not TBB", response.data['error'])

    def test_create_cash_payment(self):
        self.client.force_authenticate(user=self.accountant)
        url = reverse('payment-list')
        data = {
            "branch": self.branch.id,
            "party": self.party.id,
            "amount": "1000.00",
            "payment_mode": PaymentReceipt.PaymentMode.CASH,
            "received_at": timezone.now().isoformat()
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify it auto-verified and created a ledger entry
        receipt = PaymentReceipt.objects.get(id=response.data['id'])
        self.assertEqual(receipt.status, PaymentReceipt.Status.VERIFIED)
        
        self.assertTrue(LedgerEntry.objects.filter(
            company=self.company, party=self.party, entry_type=LedgerEntry.EntryType.CREDIT, reference_id=receipt.id
        ).exists())

    def test_verify_bank_payment(self):
        self.client.force_authenticate(user=self.accountant)
        
        # Create Pending Bank Payment
        receipt = PaymentReceipt.objects.create(
            company=self.company, branch=self.branch, party=self.party,
            amount=500, payment_mode=PaymentReceipt.PaymentMode.BANK_TRANSFER,
            status=PaymentReceipt.Status.PENDING, received_at=timezone.now()
        )
        
        url = reverse('payment-verify-bank-payment', kwargs={'pk': receipt.id})
        data = {
            "status": BankPaymentVerification.Status.VERIFIED,
            "notes": "Looks good"
        }
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, PaymentReceipt.Status.VERIFIED)
        
        self.assertTrue(BankPaymentVerification.objects.filter(payment_receipt=receipt).exists())
        self.assertTrue(LedgerEntry.objects.filter(
            company=self.company, party=self.party, entry_type=LedgerEntry.EntryType.CREDIT, reference_id=receipt.id
        ).exists())
