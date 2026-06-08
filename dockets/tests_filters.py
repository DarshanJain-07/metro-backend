from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import Company, State, City, Branch, Role, UserMembership
from dockets.models import Docket
from rest_framework.test import APIClient
from django.urls import reverse

User = get_user_model()

class DocketFilterTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Test Company")
        self.state = State.objects.create(name="Test State", code="TS")
        self.city = City.objects.create(name="Test City", state=self.state)
        self.branch = Branch.objects.create(company=self.company, name="Test Branch", city=self.city)
        self.user = User.objects.create_user(username="testuser", password="password", company=self.company, branch=self.branch)
        
        UserMembership.objects.create(
            user=self.user,
            company=self.company,
            branch=self.branch,
            role=Role.BRANCH_ADMIN
        )
        self.client.force_authenticate(user=self.user)
        
        # Create dockets with different dates
        Docket.objects.create(
            company=self.company,
            docket_no="D001",
            date="2026-05-25",
            from_city=self.city,
            to_city=self.city,
            origin_branch=self.branch,
            destination_branch=self.branch,
            consignor_name="Consignor",
            consignor_city=self.city,
            consignor_phone="1234567890",
            consignor_address="Address",
            consignee_name="Consignee",
            consignee_city=self.city,
            consignee_phone="0987654321",
            consignee_address="Address",
            total_actual_weight=Decimal("10.00"),
            total_charge_weight=Decimal("10.00")
        )
        Docket.objects.create(
            company=self.company,
            docket_no="D002",
            date="2026-06-03",
            from_city=self.city,
            to_city=self.city,
            origin_branch=self.branch,
            destination_branch=self.branch,
            consignor_name="Consignor",
            consignor_city=self.city,
            consignor_phone="1234567890",
            consignor_address="Address",
            consignee_name="Consignee",
            consignee_city=self.city,
            consignee_phone="0987654321",
            consignee_address="Address",
            total_actual_weight=Decimal("10.00"),
            total_charge_weight=Decimal("10.00")
        )

    def test_filter_with_dmy_format(self):
        url = reverse('docket-list')
        # Use DD/MM/YYYY format
        response = self.client.get(url, {
            'from_date': '25/05/2026',
            'to_date': '03/06/2026'
        })
        
        print(f"Response data: {response.data}")
        self.assertEqual(response.status_code, 200)
        # Should find both dockets
        self.assertEqual(len(response.data['results']), 2)

    def test_filter_with_iso_format(self):
        url = reverse('docket-list')
        # Use YYYY-MM-DD format
        response = self.client.get(url, {
            'from_date': '2026-05-25',
            'to_date': '2026-06-03'
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
