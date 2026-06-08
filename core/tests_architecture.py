from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import City, Company, CompanyOffice, GlobalOffice, OfficeStatus, Party, Role, State, User, UserMembership


class OfficeRegistryArchitectureTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Metro Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)

    def test_company_office_is_copy_not_live_mirror(self):
        global_office = GlobalOffice.objects.create(
            name="Dolphin Delhi",
            city=self.city,
            address="Old address",
            phone="1111111111",
            status=OfficeStatus.ACTIVE,
        )
        company_office = CompanyOffice.copy_from_global(self.company, global_office)
        company_office.save()

        global_office.address = "New registry address"
        global_office.phone = "2222222222"
        global_office.save()

        company_office.refresh_from_db()
        self.assertEqual(company_office.address, "Old address")
        self.assertEqual(company_office.phone, "1111111111")

    def test_manual_refresh_from_global_is_explicit(self):
        global_office = GlobalOffice.objects.create(
            name="Patel Jaipur",
            city=self.city,
            address="Old address",
            phone="1111111111",
        )
        company_office = CompanyOffice.copy_from_global(self.company, global_office)
        company_office.save()

        global_office.address = "Updated address"
        global_office.save()
        company_office.refresh_from_global(fields=["address"])

        company_office.refresh_from_db()
        self.assertEqual(company_office.address, "Updated address")


class PartyMasterDataApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Metro Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.user = User.objects.create_user(username="party_admin", password="pw", company=self.company)
        UserMembership.objects.create(user=self.user, company=self.company, role=Role.CLIENT_SUPER_ADMIN)

    def response_items(self, response):
        return response.data.get("results", response.data)

    def test_parties_include_and_search_address(self):
        party = Party.objects.create(
            company=self.company,
            name="Reliance Ind",
            phone="9988776655",
            address="Andheri Logistics Park",
            city=self.city,
        )
        Party.objects.create(
            company=self.company,
            name="Tata Steel",
            phone="8877665544",
            address="Powai Warehouse",
            city=self.city,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("master-list", kwargs={"resource": "parties"}), {"search": "Andheri"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = self.response_items(response)
        self.assertEqual([item["id"] for item in items], [party.id])
        self.assertEqual(items[0]["address"], "Andheri Logistics Park")
