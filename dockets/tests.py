from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import Company, State, City, Branch
from core.views import MasterDataViewSet
from dockets.models import Docket, DocketLineItem
from dockets.serializers import DocketLineItemSerializer, DocketSerializer
from rest_framework.test import APIRequestFactory, force_authenticate

User = get_user_model()

class DocketNestedUpdateTestCase(TestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Test Company")
        self.state = State.objects.create(name="Test State", code="TS")
        self.city = City.objects.create(name="Test City", state=self.state)
        self.branch = Branch.objects.create(company=self.company, name="Test Branch", city=self.city)
        self.user = User.objects.create_user(username="testuser", password="password", company=self.company, branch=self.branch)
        
        self.docket = Docket.objects.create(
            company=self.company,
            docket_no="D001",
            date="2024-01-01",
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
        self.line_item = DocketLineItem.objects.create(
            docket=self.docket,
            rate_type=DocketLineItem.RateTypeChoices.PER_PIECE,
            pieces=10,
            rate=Decimal("10.00"),
            charge=Decimal("100.00"),
            actual_weight=Decimal("10.00"),
            charged_weight=Decimal("10.00")
        )

    def valid_line_item_payload(self, **overrides):
        payload = {
            'item_type': DocketLineItem.ItemTypeChoices.GENERAL,
            'package_type': DocketLineItem.PackageTypeChoices.BOX,
            'rate_type': DocketLineItem.RateTypeChoices.PER_PIECE,
            'pieces': 10,
            'actual_weight': Decimal("10.00"),
            'charged_weight': Decimal("10.00"),
            'rate': Decimal("10.00"),
            'charge': Decimal("100.00"),
        }
        payload.update(overrides)
        return payload

    def valid_docket_payload(self, **overrides):
        payload = {
            'date': '2024-01-02',
            'status': Docket.StatusChoices.DRAFT,
            'to_city': self.city.id,
            'destination_branch': self.branch.id,
            'basis': Docket.BasisChoices.WEIGHT,
            'payment_type': Docket.PaymentTypeChoices.PAID,
            'mode': Docket.ModeChoices.ROAD,
            'delivery_type': Docket.DeliveryTypeChoices.DOOR,
            'consignor_name': 'Consignor',
            'consignor_city': self.city.id,
            'consignor_phone': '1234567890',
            'consignor_address': 'Address',
            'consignee_name': 'Consignee',
            'consignee_city': self.city.id,
            'consignee_phone': '0987654321',
            'consignee_address': 'Address',
            'gst_party': 'Consignor',
            'additional_charges': Decimal("0.00"),
            'delivery_charge': Decimal("0.00"),
            'advance_amount': Decimal("0.00"),
            'line_items': [self.valid_line_item_payload()],
        }
        payload.update(overrides)
        return payload

    def test_line_item_serializer_validate_merge_existing_data(self):
        # Test that partial update validates correctly by merging existing data
        serializer = DocketLineItemSerializer(
            instance=self.line_item, 
            data={'rate': Decimal('20.00'), 'charge': Decimal('200.00')}, 
            partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        
        # Test that inconsistent partial update fails
        serializer = DocketLineItemSerializer(
            instance=self.line_item, 
            data={'rate': Decimal('20.00'), 'charge': Decimal('100.00')}, 
            partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('charge', serializer.errors)

    def test_docket_update_rejects_unknown_line_item_id(self):
        # Test that updating with an unknown line item ID raises ValidationError in update()
        unknown_id = "01ARZ3NDEKTSV4RRFFQ6KHNQZS"
        data = {
            'line_items': [
                {'id': self.line_item.id, 'rate': Decimal('20.00'), 'charge': Decimal('200.00')},
                {'id': unknown_id, 'rate': Decimal('10.00'), 'charge': Decimal('100.00'), 'charged_weight': Decimal('10.00')} # Unknown ID
            ]
        }
        serializer = DocketSerializer(
            instance=self.docket,
            data=data,
            partial=True,
            context={'request': type('Request', (), {'user': self.user, 'method': 'PATCH'})}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('line_items', serializer.errors)
        error_msg = serializer.errors['line_items']
        if isinstance(error_msg, list):
            error_msg = str(error_msg[0])
        else:
            error_msg = str(error_msg)
        self.assertEqual(error_msg, f"Line item with ID {unknown_id} does not exist on this docket.")

    def test_docket_create_rejects_line_item_id(self):
        data = self.valid_docket_payload(
            line_items=[self.valid_line_item_payload(id=self.line_item.id)]
        )
        serializer = DocketSerializer(
            data=data,
            context={'request': type('Request', (), {'user': self.user, 'method': 'POST'})}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('line_items', serializer.errors)

    def test_docket_update_rejects_line_item_id_from_another_docket(self):
        other_docket = Docket.objects.create(
            company=self.company,
            docket_no="D002",
            date="2024-01-01",
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
        other_line_item = DocketLineItem.objects.create(
            docket=other_docket,
            rate_type=DocketLineItem.RateTypeChoices.PER_PIECE,
            pieces=10,
            rate=Decimal("10.00"),
            charge=Decimal("100.00"),
            actual_weight=Decimal("10.00"),
            charged_weight=Decimal("10.00")
        )
        data = {
            'line_items': [self.valid_line_item_payload(id=other_line_item.id)]
        }
        serializer = DocketSerializer(
            instance=self.docket,
            data=data,
            partial=True,
            context={'request': type('Request', (), {'user': self.user, 'method': 'PATCH'})}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('line_items', serializer.errors)

    def test_docket_serializer_does_not_own_optimistic_concurrency_control(self):
        old_updated_at = "2023-01-01T00:00:00Z"
        
        data = {
            'updated_at': old_updated_at,
            'consignor_name': 'New Name'
        }
        
        request = type('Request', (), {'user': self.user, 'method': 'PATCH', 'data': data})
        
        serializer = DocketSerializer(
            instance=self.docket,
            data=data,
            partial=True,
            context={'request': request}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        docket = serializer.save()

        self.assertEqual(docket.consignor_name, 'New Name')


class MasterDataPermissionTestCase(TestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Test Company")
        self.user = User.objects.create_user(username="normaluser", password="password", company=self.company)

    def test_state_create_requires_model_permission_or_admin_role(self):
        request = APIRequestFactory().post('/api/v1/master/states/', {'name': 'Blocked', 'code': 'BL'}, format='json')
        force_authenticate(request, user=self.user)

        response = MasterDataViewSet.as_view({'post': 'create'})(request, resource='states')

        self.assertEqual(response.status_code, 403)
