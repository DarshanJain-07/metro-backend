from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import City, Company, CompanyOffice, Role, State, User, UserMembership
from core.tenant_context import resolve_active_tenant_context


class ActiveTenantContextTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Metro Logistics")
        self.other_company = Company.objects.create(name="Other Logistics")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.office = CompanyOffice.objects.create(
            company=self.company,
            name="Mumbai Office",
            city=self.city,
        )
        self.other_office = CompanyOffice.objects.create(
            company=self.other_company,
            name="Other Office",
            city=self.city,
        )
        self.user = User.objects.create_user(
            username="branch_user",
            password="password",
            company=self.company,
            office=self.office,
        )
        UserMembership.objects.create(
            user=self.user,
            company=self.company,
            office=self.office,
            role=Role.VIEWER,
        )

    def test_resolves_context_for_active_membership_headers(self):
        context = resolve_active_tenant_context(
            self.user,
            company_id=self.company.id,
            office_id=self.office.id,
        )

        self.assertEqual(context.company, self.company)
        self.assertEqual(context.office, self.office)
        self.assertEqual(context.role, Role.VIEWER)

    def test_rejects_client_controlled_company_header_without_membership(self):
        with self.assertRaisesMessage(ValidationError, "Invalid active company context."):
            resolve_active_tenant_context(
                self.user,
                company_id=self.other_company.id,
                office_id=self.office.id,
            )

    def test_rejects_client_controlled_office_header_without_membership(self):
        with self.assertRaisesMessage(ValidationError, "Invalid active office context."):
            resolve_active_tenant_context(
                self.user,
                company_id=self.company.id,
                office_id=self.other_office.id,
            )

    def test_requires_explicit_context_for_multi_membership_users(self):
        UserMembership.objects.create(
            user=self.user,
            company=self.other_company,
            office=self.other_office,
            role=Role.VIEWER,
        )

        with self.assertRaisesMessage(ValidationError, "Active company/office context required."):
            resolve_active_tenant_context(self.user)
