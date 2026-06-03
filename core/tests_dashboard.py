from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from core.models import Company, Branch, City, State, Role, UserMembership
from dockets.models import Docket
from accounts.models import Invoice
from decimal import Decimal
import datetime

User = get_user_model()

class DashboardStatsTests(APITestCase):
    def setUp(self):
        self.state = State.objects.create(name='Test State', code='TS')
        self.city = City.objects.create(name='Test City', state=self.state)

        self.company = Company.objects.create(name='Test Company')
        self.branch = Branch.objects.create(name='Test Branch', company=self.company, city=self.city)

        self.user = User.objects.create_user(username='testuser', password='password', company=self.company)
        UserMembership.objects.create(user=self.user, company=self.company, branch=self.branch, role=Role.CLIENT_SUPER_ADMIN, is_active=True)
        
        self.client.force_authenticate(user=self.user)

        # Create some dockets
        self.docket = Docket.objects.create(
            company=self.company,
            docket_no='D1',
            date=datetime.date.today(),
            from_city=self.city,
            to_city=self.city,
            origin_branch=self.branch,
            destination_branch=self.branch,
            consignor_name='C1',
            consignor_phone='1234567890',
            consignor_city=self.city,
            consignor_address='Addr1',
            consignee_name='CE1',
            consignee_phone='0987654321',
            consignee_city=self.city,
            consignee_address='Addr2',
            gst_party='Consignor',
            total_actual_weight=Decimal('10.00'),
            total_charge_weight=Decimal('10.00'),
            freight=Decimal('100.00'),
            additional_charges=Decimal('10.00'),
            delivery_charge=Decimal('5.00')
        )
        # final_freight should be 115.00

    def test_dashboard_stats_success(self):
        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        
        self.assertEqual(data['total_dockets'], 1)
        self.assertEqual(len(data['recent_dockets']), 1)
        
        recent_docket = data['recent_dockets'][0]
        self.assertEqual(recent_docket['docket_no'], 'D1')
        self.assertEqual(Decimal(str(recent_docket['total_amount'])), Decimal('115.00'))
        self.assertIn('status', recent_docket)
        self.assertIn('date', recent_docket)

    def test_dashboard_stats_filtering(self):
        # Create another company and docket
        other_company = Company.objects.create(name='Other Company')
        other_branch = Branch.objects.create(name='Other Branch', company=other_company, city=self.city)
        Docket.objects.create(
            company=other_company,
            docket_no='D2',
            date=datetime.date.today(),
            from_city=self.city,
            to_city=self.city,
            origin_branch=other_branch,
            destination_branch=other_branch,
            consignor_name='C2',
            consignor_phone='1234567890',
            consignor_city=self.city,
            consignor_address='Addr2',
            consignee_name='CE2',
            consignee_phone='0987654321',
            consignee_city=self.city,
            consignee_address='Addr2',
            gst_party='Consignor',
            total_actual_weight=Decimal('10.00'),
            total_charge_weight=Decimal('10.00'),
            freight=Decimal('200.00')
        )

        url = reverse('dashboard-stats')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should still only see 1 docket from 'Test Company'
        self.assertEqual(response.data['total_dockets'], 1)
