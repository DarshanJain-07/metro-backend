from django.test import TestCase
from django.db import connection
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    City,
    Company,
    CompanyOffice,
    CompanyRolePermissionOverride,
    GlobalOffice,
    MasterScope,
    OfficeStatus,
    Party,
    Role,
    State,
    User,
    UserMembership,
)
from accounts.models import BankPaymentVerification, Expense, Invoice, InvoiceLine, LedgerEntry, PaymentReceipt
from shipments.models import (
    DeliveryAssignment,
    OfficeRatePolicy,
    ProofOfDelivery,
    RateCard,
    RateRule,
    Shipment,
    ShipmentEvent,
    ShipmentLineItem,
    ShipmentSequence,
)


TENANT_OWNED_MODELS = [
    CompanyOffice,
    CompanyRolePermissionOverride,
    Party,
    UserMembership,
    Shipment,
    ShipmentLineItem,
    ShipmentEvent,
    DeliveryAssignment,
    ProofOfDelivery,
    RateCard,
    RateRule,
    OfficeRatePolicy,
    ShipmentSequence,
    Invoice,
    InvoiceLine,
    PaymentReceipt,
    BankPaymentVerification,
    LedgerEntry,
    Expense,
]


TENANT_OWNED_TABLES = [
    "core_companyoffice",
    "core_companyrolepermissionoverride",
    "core_party",
    "core_usermembership",
    "shipments_deliveryassignment",
    "shipments_officeratepolicy",
    "shipments_proofofdelivery",
    "shipments_ratecard",
    "shipments_raterule",
    "shipments_shipment",
    "shipments_shipmentevent",
    "shipments_shipmentlineitem",
    "shipments_shipmentsequence",
    "accounts_bankpaymentverification",
    "accounts_expense",
    "accounts_invoice",
    "accounts_invoiceline",
    "accounts_ledgerentry",
    "accounts_paymentreceipt",
]


class TenantArchitectureTests(TestCase):
    def test_tenant_owned_models_have_direct_company_field(self):
        missing = []
        for model in TENANT_OWNED_MODELS:
            field_names = {field.name for field in model._meta.fields}
            if "company" not in field_names:
                missing.append(model._meta.label)

        self.assertEqual(missing, [])

    def test_tenant_owned_tables_use_composite_database_primary_key(self):
        with connection.cursor() as cursor:
            for table in TENANT_OWNED_TABLES:
                constraints = connection.introspection.get_constraints(cursor, table)
                primary_keys = [
                    constraint
                    for constraint in constraints.values()
                    if constraint.get("primary_key")
                ]
                self.assertEqual(len(primary_keys), 1, table)
                self.assertEqual(primary_keys[0]["columns"], ["company_id", "id"], table)

    def test_tenant_owned_unique_constraints_include_company(self):
        with connection.cursor() as cursor:
            for table in TENANT_OWNED_TABLES:
                constraints = connection.introspection.get_constraints(cursor, table)
                invalid = [
                    name
                    for name, constraint in constraints.items()
                    if constraint.get("unique")
                    and not constraint.get("primary_key")
                    and "company_id" not in constraint.get("columns", [])
                ]
                self.assertEqual(invalid, [], table)


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

    def test_company_directory_lists_external_companies_without_offices(self):
        empty_company = Company.objects.create(name="Pune Direct")
        inactive_company = Company.objects.create(name="Inactive Carrier", is_active=False)

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            reverse("master-list", kwargs={"resource": "companies"}),
            {"include_inactive": "false", "ordering": "name"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.data.get("results", response.data)
        names = {item["name"] for item in items}
        self.assertIn(self.other_company.name, names)
        self.assertIn(empty_company.name, names)
        self.assertNotIn(self.company.name, names)
        self.assertNotIn(inactive_company.name, names)
        self.assertNotIn("signup_code", items[0])

    def test_company_directory_includes_platform_owner_company_for_clients(self):
        owner_company = Company.objects.create(name="Metro Bootstrap", is_active=False)
        User.objects.create_user(
            username="bootstrap_owner",
            password="pw",
            company=owner_company,
            is_owner=True,
        )
        client_company = Company.objects.create(name="Client Carrier")
        client_user = User.objects.create_user(
            username="client_owner",
            password="pw",
            company=client_company,
        )
        UserMembership.objects.create(
            user=client_user,
            company=client_company,
            role=Role.SUPER_ADMIN,
        )

        self.client.force_authenticate(user=client_user)
        response = self.client.get(
            reverse("master-list", kwargs={"resource": "companies"}),
            {"include_inactive": "false", "ordering": "name"},
            HTTP_X_COMPANY_ID=str(client_company.id),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {item["name"] for item in response.data.get("results", response.data)}
        self.assertIn(owner_company.name, names)
        self.assertNotIn(client_company.name, names)

    def test_office_list_includes_owner_company_debug_field(self):
        office = CompanyOffice.objects.create(
            company=self.company,
            name="Metro Mumbai Hub",
            city=self.city,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("master-list", kwargs={"resource": "offices"}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.data.get("results", response.data)
        item = next(row for row in items if row["id"] == office.id)
        self.assertNotIn("company_name", item)
        self.assertNotIn("office_type", item)
        self.assertIsNone(item["owner_company_name"])

    def test_office_list_can_filter_to_own_company_offices(self):
        own_office = CompanyOffice.objects.create(
            company=self.company,
            name="Metro Own Hub",
            city=self.city,
            office_type=CompanyOffice.OfficeType.OWN,
        )
        current_company_global = GlobalOffice.objects.create(
            name="Metro Partner-Marked Hub",
            city=self.city,
            owner_company=self.company,
        )
        partner_marked_own_office = CompanyOffice.objects.create(
            company=self.company,
            global_office=current_company_global,
            name="Metro Partner-Marked Hub",
            city=self.city,
            office_type=CompanyOffice.OfficeType.PARTNER,
        )
        partner_global = GlobalOffice.objects.create(
            name="Swift Partner Hub",
            city=self.city,
            owner_company=self.other_company,
        )
        partner_office = CompanyOffice.objects.create(
            company=self.company,
            global_office=partner_global,
            name="Swift Partner Hub",
            city=self.city,
            office_type=CompanyOffice.OfficeType.PARTNER,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(
            reverse("master-list", kwargs={"resource": "offices"}),
            {"own_company_only": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item_ids = {item["id"] for item in response.data.get("results", response.data)}
        self.assertIn(own_office.id, item_ids)
        self.assertIn(partner_marked_own_office.id, item_ids)
        self.assertNotIn(partner_office.id, item_ids)


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
