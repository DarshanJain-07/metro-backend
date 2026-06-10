from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import City, Company, CompanyOffice, Role, State, UserMembership
from core.policies import can_view_shipment
from shipments.models import RateCard, RateRule, Shipment, ShipmentEvent, ShipmentLineItem
from shipments.services import ShipmentWorkflowService

User = get_user_model()


class ShipmentArchitectureTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Metro Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.origin = CompanyOffice.objects.create(company=self.company, name="Mumbai Office", city=self.city)
        self.destination = CompanyOffice.objects.create(company=self.company, name="Delhi Partner", city=self.city)
        self.transit = CompanyOffice.objects.create(company=self.company, name="Nagpur Transit", city=self.city)
        self.origin_user = User.objects.create_user(username="origin", password="pw", company=self.company, office=self.origin)
        self.transit_user = User.objects.create_user(username="transit", password="pw", company=self.company, office=self.transit)
        UserMembership.objects.create(user=self.origin_user, company=self.company, office=self.origin, role=Role.BOOKING_USER)
        UserMembership.objects.create(user=self.transit_user, company=self.company, office=self.transit, role=Role.DELIVERY_USER)

        self.shipment = Shipment.objects.create(
            company=self.company,
            lr_no="LR001",
            date=timezone.now().date(),
            from_city=self.city,
            origin_office=self.origin,
            to_city=self.city,
            destination_office=self.destination,
            consignor_name="Sender",
            consignor_city=self.city,
            consignor_phone="1234567890",
            consignee_name="Receiver",
            consignee_city=self.city,
            consignee_phone="1234567890",
            total_actual_weight=Decimal("10.00"),
            total_charge_weight=Decimal("10.00"),
        )
        ShipmentLineItem.objects.create(
            shipment=self.shipment,
            pieces=1,
            actual_weight=Decimal("10.00"),
            charged_weight=Decimal("10.00"),
            rate=Decimal("100.00"),
            charge=Decimal("100.00"),
        )

    def test_intermediate_office_participates_through_events(self):
        self.assertFalse(can_view_shipment(self.transit_user, self.shipment))

        ShipmentWorkflowService.record_event(
            self.shipment,
            ShipmentEvent.EventType.RECEIVED,
            self.origin_user,
            office=self.transit,
        )

        self.assertTrue(can_view_shipment(self.transit_user, self.shipment))

    def test_shipment_references_company_offices_only(self):
        self.assertEqual(self.shipment.origin_office, self.origin)
        self.assertEqual(self.shipment.destination_office, self.destination)
        self.assertFalse(hasattr(self.shipment, "global_office_id"))


class ShipmentLifecycleApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Metro Express")
        self.other_company = Company.objects.create(name="Other Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.origin = CompanyOffice.objects.create(company=self.company, name="Mumbai Office", city=self.city)
        self.destination = CompanyOffice.objects.create(company=self.company, name="Delhi Office", city=self.city)
        self.transit = CompanyOffice.objects.create(company=self.company, name="Nagpur Transit", city=self.city)
        self.other_office = CompanyOffice.objects.create(company=self.other_company, name="Other Office", city=self.city)
        self.booking_user = User.objects.create_user(username="booking_api", password="pw", company=self.company, office=self.origin)
        self.transit_user = User.objects.create_user(username="transit_api", password="pw", company=self.company, office=self.transit)
        self.branch_admin = User.objects.create_user(username="branch_admin_api", password="pw", company=self.company, office=self.origin)
        self.accountant = User.objects.create_user(username="shipment_accountant_api", password="pw", company=self.company, office=self.origin)
        self.admin_user = User.objects.create_user(username="admin_api", password="pw", company=self.company)
        UserMembership.objects.create(user=self.booking_user, company=self.company, office=self.origin, role=Role.BOOKING_USER)
        UserMembership.objects.create(user=self.transit_user, company=self.company, office=self.transit, role=Role.DELIVERY_USER)
        UserMembership.objects.create(user=self.branch_admin, company=self.company, office=self.origin, role=Role.BRANCH_ADMIN)
        UserMembership.objects.create(user=self.accountant, company=self.company, office=self.origin, role=Role.ACCOUNTANT)
        UserMembership.objects.create(user=self.admin_user, company=self.company, role=Role.CLIENT_SUPER_ADMIN)

    def shipment_payload(self):
        return {
            "date": timezone.now().date().isoformat(),
            "from_city": self.city.id,
            "origin_office": self.origin.id,
            "to_city": self.city.id,
            "destination_office": self.destination.id,
            "basis": Shipment.BasisChoices.WEIGHT,
            "payment_type": Shipment.PaymentTypeChoices.PAID,
            "mode": Shipment.ModeChoices.ROAD,
            "delivery_type": Shipment.DeliveryTypeChoices.DOOR,
            "consignor_name": "Sender",
            "consignor_city": self.city.id,
            "consignor_phone": "1234567890",
            "consignee_name": "Receiver",
            "consignee_city": self.city.id,
            "consignee_phone": "1234567890",
            "advance_amount": "0.00",
            "total_actual_weight": "10.00",
            "total_charge_weight": "10.00",
            "line_items": [
                {
                    "pieces": 1,
                    "actual_weight": "10.00",
                    "charged_weight": "10.00",
                    "rate": "100.00",
                    "charge": "100.00",
                    "rate_type": ShipmentLineItem.RateTypeChoices.PER_KG,
                }
            ],
        }

    def make_shipment(self, **kwargs):
        defaults = {
            "company": self.company,
            "lr_no": kwargs.pop("lr_no", f"LR{Shipment.objects.count() + 1:03d}"),
            "date": timezone.now().date(),
            "from_city": self.city,
            "origin_office": self.origin,
            "to_city": self.city,
            "destination_office": self.destination,
            "consignor_name": "Sender",
            "consignor_city": self.city,
            "consignor_phone": "1234567890",
            "consignee_name": "Receiver",
            "consignee_city": self.city,
            "consignee_phone": "1234567890",
            "total_actual_weight": Decimal("10.00"),
            "total_charge_weight": Decimal("10.00"),
        }
        defaults.update(kwargs)
        return Shipment.objects.create(**defaults)

    def response_items(self, response):
        return response.data.get("results", response.data)

    def test_create_books_shipment_and_records_single_booked_event(self):
        self.client.force_authenticate(user=self.booking_user)
        response = self.client.post(reverse("shipment-list"), self.shipment_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        shipment = Shipment.objects.get(id=response.data["id"])
        self.assertEqual(shipment.status, Shipment.StatusChoices.BOOKED)
        self.assertEqual(shipment.events.count(), 1)
        self.assertEqual(shipment.events.get().event_type, ShipmentEvent.EventType.BOOKED)

    def test_super_admin_lists_all_company_branch_shipments(self):
        origin_shipment = self.make_shipment(lr_no="LR-ORIGIN", origin_office=self.origin, destination_office=self.destination)
        transit_shipment = self.make_shipment(lr_no="LR-TRANSIT", origin_office=self.transit, destination_office=self.destination)

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("shipment-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in self.response_items(response)}
        self.assertIn(origin_shipment.id, ids)
        self.assertIn(transit_shipment.id, ids)

    def test_branch_admin_lists_only_own_branch_shipments(self):
        origin_shipment = self.make_shipment(lr_no="LR-BRANCH", origin_office=self.origin, destination_office=self.destination)
        other_branch_shipment = self.make_shipment(lr_no="LR-OTHER-BRANCH", origin_office=self.transit, destination_office=self.destination)

        self.client.force_authenticate(user=self.branch_admin)
        response = self.client.get(reverse("shipment-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in self.response_items(response)}
        self.assertIn(origin_shipment.id, ids)
        self.assertNotIn(other_branch_shipment.id, ids)

    def test_booking_user_can_view_but_not_update_existing_shipment(self):
        shipment = self.make_shipment(lr_no="LR-BOOKING-READONLY", origin_office=self.origin, destination_office=self.destination)

        self.client.force_authenticate(user=self.booking_user)
        retrieve_response = self.client.get(reverse("shipment-detail", kwargs={"pk": shipment.id}))
        update_response = self.client.patch(
            reverse("shipment-detail", kwargs={"pk": shipment.id}),
            {"notes": "Should not change", "updated_at": shipment.updated_at.isoformat()},
            format="json",
        )
        dispatch_response = self.client.post(reverse("shipment-dispatch", kwargs={"pk": shipment.id}), {}, format="json")

        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(dispatch_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delivery_user_can_update_delivery_workflow_only(self):
        shipment = self.make_shipment(
            lr_no="LR-DELIVERY-ONLY",
            status=Shipment.StatusChoices.RECEIVED,
            origin_office=self.origin,
            destination_office=self.transit,
        )

        self.client.force_authenticate(user=self.transit_user)
        create_response = self.client.post(reverse("shipment-list"), self.shipment_payload(), format="json")
        update_response = self.client.patch(
            reverse("shipment-detail", kwargs={"pk": shipment.id}),
            {"notes": "Should not change", "updated_at": shipment.updated_at.isoformat()},
            format="json",
        )
        delivered_response = self.client.post(
            reverse("shipment-mark-delivered", kwargs={"pk": shipment.id}),
            {"received_by_name": "Receiver", "received_by_phone": "1234567890"},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delivered_response.status_code, status.HTTP_200_OK)

    def test_delivery_user_cannot_use_general_shipment_list(self):
        self.make_shipment(lr_no="LR-DELIVERY-LIST", origin_office=self.origin, destination_office=self.transit)

        self.client.force_authenticate(user=self.transit_user)
        list_response = self.client.get(reverse("shipment-list"))
        incoming_response = self.client.get(reverse("shipment-incoming"))

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(incoming_response.status_code, status.HTTP_200_OK)

    def test_accountant_cannot_write_shipment_functions(self):
        shipment = self.make_shipment(lr_no="LR-ACCOUNTANT-BLOCKED", origin_office=self.origin, destination_office=self.destination)

        self.client.force_authenticate(user=self.accountant)
        list_response = self.client.get(reverse("shipment-list"))
        create_response = self.client.post(reverse("shipment-list"), self.shipment_payload(), format="json")
        update_response = self.client.patch(
            reverse("shipment-detail", kwargs={"pk": shipment.id}),
            {"notes": "Should not change", "updated_at": shipment.updated_at.isoformat()},
            format="json",
        )

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_book_rejects_already_booked_created_shipment_without_duplicate_event(self):
        self.client.force_authenticate(user=self.booking_user)
        create_response = self.client.post(reverse("shipment-list"), self.shipment_payload(), format="json")
        shipment_id = create_response.data["id"]

        response = self.client.post(reverse("shipment-book", kwargs={"pk": shipment_id}), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        shipment = Shipment.objects.get(id=shipment_id)
        self.assertEqual(shipment.status, Shipment.StatusChoices.BOOKED)
        self.assertEqual(shipment.events.filter(event_type=ShipmentEvent.EventType.BOOKED).count(), 1)

    def test_incoming_uses_destination_or_latest_received_event_only(self):
        destination_shipment = self.make_shipment(lr_no="LR-IN-DEST", status=Shipment.StatusChoices.BOOKED, destination_office=self.transit)
        latest_received = self.make_shipment(lr_no="LR-IN-LATEST", status=Shipment.StatusChoices.RECEIVED)
        historical_only = self.make_shipment(lr_no="LR-OLD-EVENT", status=Shipment.StatusChoices.IN_TRANSIT)
        delivered = self.make_shipment(lr_no="LR-DELIVERED", status=Shipment.StatusChoices.DELIVERED, destination_office=self.transit)
        cancelled = self.make_shipment(lr_no="LR-CANCELLED", status=Shipment.StatusChoices.CANCELLED, destination_office=self.transit)

        older_time = timezone.now() - timezone.timedelta(minutes=5)
        newer_time = timezone.now()
        ShipmentWorkflowService.record_event(
            latest_received,
            ShipmentEvent.EventType.RECEIVED,
            self.booking_user,
            office=self.transit,
            occurred_at=newer_time,
        )
        ShipmentWorkflowService.record_event(
            historical_only,
            ShipmentEvent.EventType.RECEIVED,
            self.booking_user,
            office=self.transit,
            occurred_at=older_time,
        )
        ShipmentWorkflowService.record_event(
            historical_only,
            ShipmentEvent.EventType.DISPATCHED,
            self.booking_user,
            office=self.origin,
            occurred_at=newer_time,
        )

        self.client.force_authenticate(user=self.transit_user)
        response = self.client.get(reverse("shipment-incoming"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in self.response_items(response)}
        self.assertIn(destination_shipment.id, ids)
        self.assertIn(latest_received.id, ids)
        self.assertNotIn(historical_only.id, ids)
        self.assertNotIn(delivered.id, ids)
        self.assertNotIn(cancelled.id, ids)

    def test_rate_rule_queryset_and_validation_are_company_scoped(self):
        card = RateCard.objects.create(company=self.company, name="Default", effective_from=timezone.now(), is_default=True)
        other_card = RateCard.objects.create(company=self.other_company, name="Other", effective_from=timezone.now(), is_default=True)
        own_rule = RateRule.objects.create(
            rate_card=card,
            origin_city=self.city,
            destination_city=self.city,
            basis=Shipment.BasisChoices.WEIGHT,
            rate_type=ShipmentLineItem.RateTypeChoices.PER_KG,
            rate=Decimal("10.00"),
        )
        RateRule.objects.create(
            rate_card=other_card,
            origin_city=self.city,
            destination_city=self.city,
            basis=Shipment.BasisChoices.WEIGHT,
            rate_type=ShipmentLineItem.RateTypeChoices.PER_KG,
            rate=Decimal("20.00"),
        )

        self.client.force_authenticate(user=self.admin_user)
        list_response = self.client.get(reverse("rate-rule-list"))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in self.response_items(list_response)}
        self.assertEqual(ids, {own_rule.id})

        create_response = self.client.post(
            reverse("rate-rule-list"),
            {
                "rate_card": other_card.id,
                "origin_city": self.city.id,
                "destination_city": self.city.id,
                "origin_office": self.other_office.id,
                "basis": Shipment.BasisChoices.WEIGHT,
                "rate_type": ShipmentLineItem.RateTypeChoices.PER_KG,
                "rate": "30.00",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_400_BAD_REQUEST)

        suggested_response = self.client.get(
            reverse("shipment-suggested-rate"),
            {"origin_office": self.origin.id, "destination_office": self.other_office.id, "basis": Shipment.BasisChoices.WEIGHT},
        )
        self.assertEqual(suggested_response.status_code, status.HTTP_404_NOT_FOUND)
