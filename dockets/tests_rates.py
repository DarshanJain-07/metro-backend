import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory
from core.models import Company, State, City, Branch, Role, UserMembership
from dockets.models import Docket, DocketLineItem, RateCard, RateRule, BranchRatePolicy
from dockets.serializers import DocketSerializer

User = get_user_model()

class RateManagementTestCase(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        
        self.company = Company.objects.create(name="Test Company")
        self.state = State.objects.create(name="Test State", code="TS")
        self.city_a = City.objects.create(name="City A", state=self.state)
        self.city_b = City.objects.create(name="City B", state=self.state)
        
        self.branch_a = Branch.objects.create(company=self.company, name="Branch A", city=self.city_a)
        self.branch_b = Branch.objects.create(company=self.company, name="Branch B", city=self.city_b)
        
        self.user = User.objects.create_user(username="testuser", password="password", company=self.company, branch=self.branch_a)
        UserMembership.objects.create(user=self.user, company=self.company, branch=self.branch_a, role=Role.BOOKING_USER)

        self.superadmin = User.objects.create_user(username="superadmin", password="password", company=self.company, is_superuser=True, branch=self.branch_a)
        
        # Create Rate Card and Rule
        now = timezone.now()
        self.rate_card = RateCard.objects.create(
            company=self.company, 
            name="Standard Rates", 
            is_default=True,
            effective_from=now - datetime.timedelta(days=1)
        )
        
        self.rate_rule = RateRule.objects.create(
            rate_card=self.rate_card,
            origin_city=self.city_a,
            destination_city=self.city_b,
            basis=Docket.BasisChoices.WEIGHT,
            rate_type=DocketLineItem.RateTypeChoices.PER_KG,
            rate=Decimal('10.00'),
            min_charge=Decimal('50.00'),
            delivery_charge=Decimal('100.00')
        )

        # Base valid docket data
        self.valid_docket_data = {
            "date": "2024-01-01",
            "docket_no": "TEST001",
            "from_city": self.city_a.id,
            "to_city": self.city_b.id,
            "origin_branch": self.branch_a.id,
            "destination_branch": self.branch_b.id,
            "consignor_name": "Consignor",
            "consignor_city": self.city_a.id,
            "consignor_phone": "1234567890",
            "consignor_address": "Address",
            "consignee_name": "Consignee",
            "consignee_city": self.city_b.id,
            "consignee_phone": "0987654321",
            "consignee_address": "Address",
            "gst_party": "Consignor",
            "basis": Docket.BasisChoices.WEIGHT,
            "delivery_charge": "100.00",
            "line_items": [
                {
                    "item_type": DocketLineItem.ItemTypeChoices.GENERAL,
                    "package_type": DocketLineItem.PackageTypeChoices.BOX,
                    "rate_type": DocketLineItem.RateTypeChoices.PER_KG,
                    "pieces": 5,
                    "actual_weight": "20.00",
                    "charged_weight": "20.00",
                    "rate": "10.00",  # Matches the rule
                    "charge": "200.00"
                }
            ]
        }

    def _get_context(self, user):
        request = self.factory.post('/')
        request.user = user
        return {'request': request}

    def test_standard_rate_applied_successfully(self):
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.user))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        docket = serializer.save(company=self.company, created_by=self.user)
        
        line_item = docket.line_items.first()
        self.assertEqual(line_item.rate_rule, self.rate_rule)
        self.assertEqual(line_item.rate, Decimal('10.00'))

    def test_branch_without_permission_cannot_override_rate(self):
        # Change rate in data
        self.valid_docket_data['line_items'][0]['rate'] = "8.00"
        self.valid_docket_data['line_items'][0]['charge'] = "160.00"
        
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.user))
        self.assertFalse(serializer.is_valid())
        self.assertIn("not allowed to override rates", str(serializer.errors['line_items']))

    def test_branch_with_permission_can_override_within_limit(self):
        # Give permission and max discount 30%
        BranchRatePolicy.objects.create(
            company=self.company,
            branch=self.branch_a,
            can_override_rate=True,
            max_discount_percent=Decimal('30.00')
        )
        
        # Rate is 10.00, override to 8.00 (20% discount)
        self.valid_docket_data['line_items'][0]['rate'] = "8.00"
        self.valid_docket_data['line_items'][0]['charge'] = "160.00"
        self.valid_docket_data['line_items'][0]['override_reason'] = "Customer requested discount"
        
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.user))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        docket = serializer.save(company=self.company, created_by=self.user)
        
        line_item = docket.line_items.first()
        self.assertEqual(line_item.rate, Decimal('8.00'))
        self.assertEqual(line_item.override_reason, "Customer requested discount")

    def test_branch_cannot_override_beyond_max_discount(self):
        BranchRatePolicy.objects.create(
            company=self.company,
            branch=self.branch_a,
            can_override_rate=True,
            max_discount_percent=Decimal('10.00') # Max 10%
        )
        
        # Override to 8.00 (20% discount) -> should fail
        self.valid_docket_data['line_items'][0]['rate'] = "8.00"
        self.valid_docket_data['line_items'][0]['charge'] = "160.00"
        self.valid_docket_data['line_items'][0]['override_reason'] = "Customer requested discount"
        
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.user))
        self.assertFalse(serializer.is_valid())
        self.assertIn("exceeds maximum allowed discount", str(serializer.errors['line_items']))

    def test_override_requires_reason(self):
        BranchRatePolicy.objects.create(
            company=self.company,
            branch=self.branch_a,
            can_override_rate=True,
            max_discount_percent=Decimal('30.00')
        )
        
        self.valid_docket_data['line_items'][0]['rate'] = "8.00"
        self.valid_docket_data['line_items'][0]['charge'] = "160.00"
        # No override_reason provided
        
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.user))
        self.assertFalse(serializer.is_valid())
        self.assertIn("Override reason is required", str(serializer.errors['line_items']))

    def test_superadmin_can_override_freely(self):
        self.valid_docket_data['line_items'][0]['rate'] = "5.00" # 50% discount
        self.valid_docket_data['line_items'][0]['charge'] = "100.00"
        # No override reason required for superadmin either technically, but let's provide one just in case 
        # or we check if super admin is bypassed completely. The current logic bypasses all checks for superadmin.
        
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.superadmin))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        docket = serializer.save(company=self.company, created_by=self.superadmin)
        self.assertEqual(docket.line_items.first().rate, Decimal('5.00'))

    def test_inactive_rate_card_is_ignored(self):
        self.rate_card.is_active = False
        self.rate_card.save()
        
        # Submitting an arbitrary rate should succeed since no active rate rule enforces anything
        self.valid_docket_data['line_items'][0]['rate'] = "15.00"
        self.valid_docket_data['line_items'][0]['charge'] = "300.00"
        
        serializer = DocketSerializer(data=self.valid_docket_data, context=self._get_context(self.user))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        docket = serializer.save(company=self.company, created_by=self.user)
        self.assertIsNone(docket.line_items.first().rate_rule)
