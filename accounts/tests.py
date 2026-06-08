from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Invoice, InvoiceLine, PaymentReceipt
from core.models import City, Company, CompanyOffice, Party, Role, State, UserMembership
from shipments.models import Shipment

User = get_user_model()


class BillingArchitectureTests(TestCase):
    def test_invoice_lines_reference_shipments(self):
        company = Company.objects.create(name="Metro Express")
        state = State.objects.create(name="Maharashtra", code="MH")
        city = City.objects.create(name="Mumbai", state=state)
        office = CompanyOffice.objects.create(company=company, name="Mumbai Office", city=city)
        party = Party.objects.create(company=company, name="Customer", phone="1234567890", city=city)
        shipment = Shipment.objects.create(
            company=company,
            lr_no="LR001",
            date=timezone.now().date(),
            from_city=city,
            origin_office=office,
            to_city=city,
            destination_office=office,
            consignor_name="Sender",
            consignor_city=city,
            consignor_phone="1234567890",
            consignee_name="Receiver",
            consignee_city=city,
            consignee_phone="1234567890",
            total_actual_weight=Decimal("10.00"),
            total_charge_weight=Decimal("10.00"),
        )
        invoice = Invoice.objects.create(
            company=company,
            office=office,
            party=party,
            invoice_no="INV001",
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total_amount=Decimal("100.00"),
        )
        line = InvoiceLine.objects.create(invoice=invoice, shipment=shipment, description="Freight", amount=Decimal("100.00"))

        self.assertEqual(line.shipment.lr_no, "LR001")
        self.assertEqual(invoice.office, office)


class BillingApiPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Metro Express")
        self.other_company = Company.objects.create(name="Other Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.office = CompanyOffice.objects.create(company=self.company, name="Mumbai Office", city=self.city)
        self.other_office = CompanyOffice.objects.create(company=self.company, name="Delhi Office", city=self.city)
        self.foreign_office = CompanyOffice.objects.create(company=self.other_company, name="Foreign Office", city=self.city)
        self.party = Party.objects.create(company=self.company, name="Customer", phone="1234567890", city=self.city)
        self.foreign_party = Party.objects.create(company=self.other_company, name="Foreign Customer", phone="1234567890", city=self.city)
        self.accountant = User.objects.create_user(username="accountant", password="pw", company=self.company, office=self.office)
        self.admin = User.objects.create_user(username="company_admin", password="pw", company=self.company)
        UserMembership.objects.create(user=self.accountant, company=self.company, office=self.office, role=Role.ACCOUNTANT)
        UserMembership.objects.create(user=self.admin, company=self.company, role=Role.CLIENT_SUPER_ADMIN)

    def make_shipment(self, **kwargs):
        defaults = {
            "company": self.company,
            "lr_no": kwargs.pop("lr_no", f"LR{Shipment.objects.count() + 1:03d}"),
            "date": timezone.now().date(),
            "from_city": self.city,
            "origin_office": self.office,
            "to_city": self.city,
            "destination_office": self.other_office,
            "payment_type": Shipment.PaymentTypeChoices.TBB,
            "consignor_name": "Sender",
            "consignor_city": self.city,
            "consignor_phone": "1234567890",
            "consignee_name": "Receiver",
            "consignee_city": self.city,
            "consignee_phone": "1234567890",
            "freight": Decimal("100.00"),
            "total_actual_weight": Decimal("10.00"),
            "total_charge_weight": Decimal("10.00"),
        }
        defaults.update(kwargs)
        return Shipment.objects.create(**defaults)

    def invoice_payload(self, office, shipment):
        return {
            "party": self.party.id,
            "office": office.id,
            "shipments": [shipment.id],
            "due_date": timezone.now().date().isoformat(),
        }

    def test_office_accountant_cannot_invoice_another_office(self):
        shipment = self.make_shipment()
        self.client.force_authenticate(user=self.accountant)

        response = self.client.post(reverse("invoice-generate"), self.invoice_payload(self.other_office, shipment), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_company_admin_can_invoice_participating_office(self):
        shipment = self.make_shipment()
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(reverse("invoice-generate"), self.invoice_payload(self.other_office, shipment), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_invoice_rejects_non_participating_office(self):
        shipment = self.make_shipment(origin_office=self.office, destination_office=self.office)
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(reverse("invoice-generate"), self.invoice_payload(self.other_office, shipment), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_invoice_rejects_already_invoiced_shipment(self):
        shipment = self.make_shipment()
        invoice = Invoice.objects.create(
            company=self.company,
            office=self.office,
            party=self.party,
            invoice_no="INV001",
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total_amount=Decimal("100.00"),
        )
        InvoiceLine.objects.create(invoice=invoice, shipment=shipment, description="Freight", amount=Decimal("100.00"))
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(reverse("invoice-generate"), self.invoice_payload(self.office, shipment), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_office_accountant_cannot_create_payment_for_another_office(self):
        self.client.force_authenticate(user=self.accountant)

        response = self.client.post(
            reverse("payment-list"),
            {
                "office": self.other_office.id,
                "party": self.party.id,
                "amount": "100.00",
                "payment_mode": PaymentReceipt.PaymentMode.CASH,
                "received_at": timezone.now().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PaymentReceipt.objects.count(), 0)

    def test_payment_rejects_foreign_office_and_party(self):
        self.client.force_authenticate(user=self.admin)

        office_response = self.client.post(
            reverse("payment-list"),
            {
                "office": self.foreign_office.id,
                "party": self.party.id,
                "amount": "100.00",
                "payment_mode": PaymentReceipt.PaymentMode.CASH,
                "received_at": timezone.now().isoformat(),
            },
            format="json",
        )
        party_response = self.client.post(
            reverse("payment-list"),
            {
                "office": self.office.id,
                "party": self.foreign_party.id,
                "amount": "100.00",
                "payment_mode": PaymentReceipt.PaymentMode.CASH,
                "received_at": timezone.now().isoformat(),
            },
            format="json",
        )

        self.assertEqual(office_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(party_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(PaymentReceipt.objects.count(), 0)
