from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from core.models import Company, Branch, City, State, Role, UserMembership
from dockets.models import Docket
from decimal import Decimal

User = get_user_model()

class MultitenancyAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.state = State.objects.create(name='Test State', code='TS')
        self.city = City.objects.create(name='Test City', state=self.state)

        # Company A
        self.company_a = Company.objects.create(name='Company A')
        self.branch_a1 = Branch.objects.create(name='Branch A1', company=self.company_a, city=self.city)
        self.branch_a2 = Branch.objects.create(name='Branch A2', company=self.company_a, city=self.city)

        # Company B
        self.company_b = Company.objects.create(name='Company B')
        self.branch_b1 = Branch.objects.create(name='Branch B1', company=self.company_b, city=self.city)

        # Users
        self.super_admin_a = User.objects.create_user(username='sa_a', password='pw', company=self.company_a)
        UserMembership.objects.create(user=self.super_admin_a, company=self.company_a, role=Role.CLIENT_SUPER_ADMIN)

        self.branch_admin_a1 = User.objects.create_user(username='ba_a1', password='pw', company=self.company_a, branch=self.branch_a1)
        UserMembership.objects.create(user=self.branch_admin_a1, company=self.company_a, branch=self.branch_a1, role=Role.BRANCH_ADMIN)

        self.booking_user_a1 = User.objects.create_user(username='bu_a1', password='pw', company=self.company_a, branch=self.branch_a1)
        UserMembership.objects.create(user=self.booking_user_a1, company=self.company_a, branch=self.branch_a1, role=Role.BOOKING_USER)

        # Data
        self.docket_a1 = Docket.objects.create(
            company=self.company_a, docket_no='A1-001', date='2024-01-01',
            from_city=self.city, to_city=self.city,
            origin_branch=self.branch_a1, destination_branch=self.branch_a1,
            consignor_name='C1', consignor_city=self.city, consignor_phone='1234567890', consignor_address='Add',
            consignee_name='C2', consignee_city=self.city, consignee_phone='1234567890', consignee_address='Add',
            total_actual_weight=Decimal('10'), total_charge_weight=Decimal('10')
        )
        self.docket_a2 = Docket.objects.create(
            company=self.company_a, docket_no='A2-001', date='2024-01-01',
            from_city=self.city, to_city=self.city,
            origin_branch=self.branch_a2, destination_branch=self.branch_a2,
            consignor_name='C1', consignor_city=self.city, consignor_phone='1234567890', consignor_address='Add',
            consignee_name='C2', consignee_city=self.city, consignee_phone='1234567890', consignee_address='Add',
            total_actual_weight=Decimal('10'), total_charge_weight=Decimal('10')
        )
        self.docket_b1 = Docket.objects.create(
            company=self.company_b, docket_no='B1-001', date='2024-01-01',
            from_city=self.city, to_city=self.city,
            origin_branch=self.branch_b1, destination_branch=self.branch_b1,
            consignor_name='C1', consignor_city=self.city, consignor_phone='1234567890', consignor_address='Add',
            consignee_name='C2', consignee_city=self.city, consignee_phone='1234567890', consignee_address='Add',
            total_actual_weight=Decimal('10'), total_charge_weight=Decimal('10')
        )

    def test_branch_user_can_only_see_own_branch_dockets(self):
        self.client.force_authenticate(user=self.branch_admin_a1)
        response = self.client.get('/api/v1/dockets/')
        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data)
        docket_nos = [d['docket_no'] for d in results]
        self.assertIn('A1-001', docket_nos)
        self.assertNotIn('A2-001', docket_nos)
        self.assertNotIn('B1-001', docket_nos)

    def test_super_admin_can_see_all_company_dockets(self):
        self.client.force_authenticate(user=self.super_admin_a)
        response = self.client.get('/api/v1/dockets/')
        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data)
        docket_nos = [d['docket_no'] for d in results]
        self.assertIn('A1-001', docket_nos)
        self.assertIn('A2-001', docket_nos)
        self.assertNotIn('B1-001', docket_nos)

    def test_branch_user_cannot_mutate_other_branch_docket(self):
        self.client.force_authenticate(user=self.branch_admin_a1)
        # Try to update docket_a2 (which is in branch_a2)
        response = self.client.patch(f'/api/v1/dockets/{self.docket_a2.id}/', {'status': 'BOOKED'})
        # Should be 404 because it's filtered out of the queryset
        self.assertEqual(response.status_code, 404)

    def test_branch_user_cannot_create_for_other_branch(self):
        self.client.force_authenticate(user=self.booking_user_a1)
        payload = {
            'docket_no': 'A2-NEW',
            'date': '2024-01-02',
            'from_city': self.city.id,
            'to_city': self.city.id,
            'origin_branch': self.branch_a2.id,
            'destination_branch': self.branch_a1.id,
            'consignor_name': 'C1',
            'consignor_city': self.city.id,
            'consignor_phone': '1234567890',
            'consignor_address': 'Add',
            'consignee_name': 'C2',
            'consignee_city': self.city.id,
            'consignee_phone': '1234567890',
            'consignee_address': 'Add',
            'gst_party': 'Consignor',
            'total_actual_weight': '10',
            'total_charge_weight': '10',
            'line_items': [{
                'item_type': Docket.LineItemTypeChoices.GENERAL if hasattr(Docket, 'LineItemTypeChoices') else 'GENERAL',
                'package_type': 'BOX',
                'rate_type': 'PER_PIECE',
                'pieces': 10,
                'actual_weight': '10',
                'charged_weight': '10',
                'rate': '10',
                'charge': '100'
            }]
        }
        response = self.client.post('/api/v1/dockets/', payload, format='json')
        # Should fail validation
        self.assertEqual(response.status_code, 400)
        self.assertIn('origin_branch', response.data)
