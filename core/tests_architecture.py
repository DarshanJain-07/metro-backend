from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    City,
    Company,
    CompanyOffice,
    GlobalOffice,
    MasterScope,
    OfficeStatus,
    Party,
    Role,
    State,
    User,
    UserMembership,
)


class OfficeRegistryArchitectureTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Metro Express")
        self.other_company = Company.objects.create(name="Swift Carriers")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.user = User.objects.create_user(username="metro_admin", password="pw", company=self.company)
        UserMembership.objects.create(user=self.user, company=self.company, role=Role.SUPER_ADMIN)

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

    def test_global_office_list_materializes_existing_company_offices(self):
        office = CompanyOffice.objects.create(
            company=self.other_company,
            name="Swift Mumbai Hub",
            city=self.city,
            address="Dock Road",
            phone="9999999999",
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            reverse("master-list", kwargs={"resource": "global-offices"}),
            {"include_inactive": "false"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.data.get("results", response.data)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Swift Mumbai Hub")
        self.assertEqual(items[0]["owner_company"], self.other_company.id)

        office.refresh_from_db()
        self.assertIsNotNone(office.global_office_id)


class PartyMasterDataApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Metro Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.branch = CompanyOffice.objects.create(company=self.company, name="Andheri", city=self.city)
        self.other_branch = CompanyOffice.objects.create(company=self.company, name="Bandra", city=self.city)
        self.user = User.objects.create_user(username="party_admin", password="pw", company=self.company)
        UserMembership.objects.create(user=self.user, company=self.company, role=Role.SUPER_ADMIN)
        self.branch_admin = User.objects.create_user(
            username="branch_party_admin",
            password="pw",
            company=self.company,
            office=self.branch,
        )
        UserMembership.objects.create(
            user=self.branch_admin,
            company=self.company,
            office=self.branch,
            role=Role.BRANCH_ADMIN,
        )
        self.other_branch_user = User.objects.create_user(
            username="other_branch_user",
            password="pw",
            company=self.company,
            office=self.other_branch,
        )
        UserMembership.objects.create(
            user=self.other_branch_user,
            company=self.company,
            office=self.other_branch,
            role=Role.VIEWER,
        )

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

    def test_branch_admin_created_party_is_branch_scoped(self):
        self.client.force_authenticate(user=self.branch_admin)
        response = self.client.post(
            reverse("master-list", kwargs={"resource": "parties"}),
            {
                "name": "Local Consignee",
                "phone": "9988776655",
                "address": "Branch customer",
                "city": self.city.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        party = Party.unscoped_objects.get(id=response.data["id"])
        self.assertEqual(party.scope_type, MasterScope.BRANCH)
        self.assertEqual(party.scope_id, self.branch.id)

        self.client.force_authenticate(user=self.user)
        super_admin_response = self.client.get(reverse("master-list", kwargs={"resource": "parties"}))
        self.assertNotIn(party.id, [item["id"] for item in self.response_items(super_admin_response)])

    def test_branch_user_sees_company_and_own_branch_master_data_only(self):
        company_party = Party.objects.create(
            company=self.company,
            name="Company Party",
            phone="1111111111",
            city=self.city,
        )
        branch_party = Party.objects.create(
            company=self.company,
            name="Branch Party",
            phone="2222222222",
            city=self.city,
            scope_type=MasterScope.BRANCH,
            scope_id=self.branch.id,
        )
        other_branch_party = Party.objects.create(
            company=self.company,
            name="Other Branch Party",
            phone="3333333333",
            city=self.city,
            scope_type=MasterScope.BRANCH,
            scope_id=self.other_branch.id,
        )

        self.client.force_authenticate(user=self.branch_admin)
        response = self.client.get(reverse("master-list", kwargs={"resource": "parties"}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in self.response_items(response)]
        self.assertIn(company_party.id, ids)
        self.assertIn(branch_party.id, ids)
        self.assertNotIn(other_branch_party.id, ids)
