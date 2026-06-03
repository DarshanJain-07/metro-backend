from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import Company, Branch, City, State, Role, UserMembership
from dockets.models import Docket
from core.policies import (
    can_manage_company, can_manage_branch, can_view_branch_data,
    can_create_docket, can_edit_docket
)

User = get_user_model()

class PolicyTests(TestCase):
    def setUp(self):
        self.state = State.objects.create(name='Test State', code='TS')
        self.city = City.objects.create(name='Test City', state=self.state)

        self.company_a = Company.objects.create(name='Company A')
        self.branch_a1 = Branch.objects.create(name='Branch A1', company=self.company_a, city=self.city)
        self.branch_a2 = Branch.objects.create(name='Branch A2', company=self.company_a, city=self.city)

        self.company_b = Company.objects.create(name='Company B')
        self.branch_b1 = Branch.objects.create(name='Branch B1', company=self.company_b, city=self.city)

        # Users
        self.platform_admin = User.objects.create_user(username='pa', password='pw')
        UserMembership.objects.create(user=self.platform_admin, company=self.company_a, role=Role.PLATFORM_ADMIN)

        self.super_admin_a = User.objects.create_user(username='sa_a', password='pw', company=self.company_a)
        UserMembership.objects.create(user=self.super_admin_a, company=self.company_a, role=Role.CLIENT_SUPER_ADMIN)

        self.branch_admin_a1 = User.objects.create_user(username='ba_a1', password='pw', company=self.company_a, branch=self.branch_a1)
        UserMembership.objects.create(user=self.branch_admin_a1, company=self.company_a, branch=self.branch_a1, role=Role.BRANCH_ADMIN)

        self.booking_user_a1 = User.objects.create_user(username='bu_a1', password='pw', company=self.company_a, branch=self.branch_a1)
        UserMembership.objects.create(user=self.booking_user_a1, company=self.company_a, branch=self.branch_a1, role=Role.BOOKING_USER)

    def test_company_isolation(self):
        # Super admin A can manage Company A but not B
        self.assertTrue(can_manage_company(self.super_admin_a, self.company_a))
        self.assertFalse(can_manage_company(self.super_admin_a, self.company_b))

        # Platform admin can manage both
        self.assertTrue(can_manage_company(self.platform_admin, self.company_a))
        self.assertTrue(can_manage_company(self.platform_admin, self.company_b))

        # Branch admin A1 cannot manage company
        self.assertFalse(can_manage_company(self.branch_admin_a1, self.company_a))

    def test_branch_isolation(self):
        # Branch admin A1 can manage Branch A1 but not A2 or B1
        self.assertTrue(can_manage_branch(self.branch_admin_a1, self.branch_a1))
        self.assertFalse(can_manage_branch(self.branch_admin_a1, self.branch_a2))
        self.assertFalse(can_manage_branch(self.branch_admin_a1, self.branch_b1))

        # Super admin A can manage A1 and A2
        self.assertTrue(can_manage_branch(self.super_admin_a, self.branch_a1))
        self.assertTrue(can_manage_branch(self.super_admin_a, self.branch_a2))
        self.assertFalse(can_manage_branch(self.super_admin_a, self.branch_b1))

    def test_docket_creation_policy(self):
        # Booking user A1 can create docket in A1 but not A2
        self.assertTrue(can_create_docket(self.booking_user_a1, self.branch_a1))
        self.assertFalse(can_create_docket(self.booking_user_a1, self.branch_a2))

        # Branch admin A1 can create in A1
        self.assertTrue(can_create_docket(self.branch_admin_a1, self.branch_a1))
