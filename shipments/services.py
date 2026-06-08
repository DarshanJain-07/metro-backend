from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.policies import (
    can,
    can_assign_delivery,
    can_book_shipment,
    can_cancel_shipment,
    can_dispatch_shipment,
    can_mark_delivered,
    can_receive_shipment,
)
from core.request_context import get_current_office
from .models import DeliveryAssignment, OfficeRatePolicy, ProofOfDelivery, RateCard, RateRule, Shipment, ShipmentEvent


def get_office_rate_policy(company, office):
    policy, _ = OfficeRatePolicy.objects.get_or_create(
        company=company,
        office=office,
        defaults={"can_override_rate": False, "max_discount_percent": Decimal("0.00")},
    )
    return policy


def lookup_rate(company, origin_office, destination_office, basis):
    now = timezone.now()
    active_cards = RateCard.objects.filter(
        company=company,
        is_active=True,
        effective_from__lte=now,
    ).filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=now)).order_by("-is_default", "-effective_from")

    for card in active_cards:
        rules = RateRule.objects.filter(rate_card=card, is_active=True, basis=basis)
        rule = rules.filter(origin_office=origin_office, destination_office=destination_office).first()
        if rule:
            return rule
        rule = rules.filter(origin_office=origin_office, destination_city=destination_office.city, destination_office__isnull=True).first()
        if rule:
            return rule
        rule = rules.filter(origin_city=origin_office.city, destination_office=destination_office, origin_office__isnull=True).first()
        if rule:
            return rule
        rule = rules.filter(
            origin_city=origin_office.city,
            destination_city=destination_office.city,
            origin_office__isnull=True,
            destination_office__isnull=True,
        ).first()
        if rule:
            return rule
    return None


class ShipmentWorkflowService:
    @staticmethod
    @transaction.atomic
    def record_event(shipment, event_type, user, office=None, notes=None, metadata=None, occurred_at=None):
        office = office or get_current_office()
        if office is None:
            raise ValidationError("Active office context required for shipment events.")
        if office.company_id != shipment.company_id:
            raise ValidationError("Event office must belong to the shipment company office master.")
        return ShipmentEvent.objects.create(
            shipment=shipment,
            event_type=event_type,
            office=office,
            actor=user,
            notes=notes,
            metadata=metadata or {},
            occurred_at=occurred_at or timezone.now(),
        )

    @staticmethod
    @transaction.atomic
    def book_shipment(shipment, user):
        if not can_book_shipment(user, shipment):
            raise ValidationError("You do not have permission to book this shipment.")
        if shipment.status != Shipment.StatusChoices.DRAFT:
            raise ValidationError(f"Cannot book shipment in {shipment.status} status.")
        shipment.status = Shipment.StatusChoices.BOOKED
        shipment.save(update_fields=["status", "updated_at", "updated_by"])
        ShipmentWorkflowService.record_event(shipment, ShipmentEvent.EventType.BOOKED, user, office=shipment.origin_office)
        return shipment

    @staticmethod
    @transaction.atomic
    def dispatch(shipment, user, office=None, notes=None):
        office = office or get_current_office() or shipment.origin_office
        if not can_dispatch_shipment(user, shipment, office):
            raise ValidationError("You do not have permission to dispatch this shipment.")
        if shipment.status in [Shipment.StatusChoices.DELIVERED, Shipment.StatusChoices.CANCELLED]:
            raise ValidationError(f"Cannot dispatch shipment in {shipment.status} status.")
        shipment.status = Shipment.StatusChoices.IN_TRANSIT
        shipment.save(update_fields=["status", "updated_at", "updated_by"])
        ShipmentWorkflowService.record_event(shipment, ShipmentEvent.EventType.DISPATCHED, user, office=office, notes=notes)
        return shipment

    @staticmethod
    @transaction.atomic
    def receive(shipment, user, office=None, notes=None):
        office = office or get_current_office()
        if office is None:
            raise ValidationError("Active office context required.")
        if not can_receive_shipment(user, shipment, office):
            raise ValidationError("You do not have permission to receive this shipment.")
        if shipment.status not in [Shipment.StatusChoices.IN_TRANSIT, Shipment.StatusChoices.BOOKED]:
            raise ValidationError(f"Cannot receive shipment from {shipment.status} status.")
        shipment.status = Shipment.StatusChoices.RECEIVED
        shipment.save(update_fields=["status", "updated_at", "updated_by"])
        ShipmentWorkflowService.record_event(shipment, ShipmentEvent.EventType.RECEIVED, user, office=office, notes=notes)
        return shipment

    @staticmethod
    @transaction.atomic
    def assign_delivery(shipment, delivery_user, assigned_by):
        if not can_assign_delivery(assigned_by, shipment):
            raise ValidationError("You do not have permission to assign delivery for this shipment.")
        if not can(delivery_user, "shipment:deliver", company=shipment.company, office=shipment.destination_office):
            raise ValidationError("Delivery user must have active delivery permission for the destination office.")
        if shipment.status != Shipment.StatusChoices.RECEIVED:
            raise ValidationError("Shipment must be received before delivery assignment.")

        DeliveryAssignment.objects.filter(shipment=shipment, status=DeliveryAssignment.StatusChoices.ASSIGNED).update(
            status=DeliveryAssignment.StatusChoices.CANCELLED,
            updated_at=timezone.now(),
            updated_by=assigned_by,
        )
        shipment.status = Shipment.StatusChoices.OUT_FOR_DELIVERY
        shipment.save(update_fields=["status", "updated_at", "updated_by"])
        ShipmentWorkflowService.record_event(
            shipment,
            ShipmentEvent.EventType.OUT_FOR_DELIVERY,
            assigned_by,
            office=shipment.destination_office,
            metadata={"delivery_user": delivery_user.id},
        )
        return DeliveryAssignment.objects.create(
            shipment=shipment,
            delivery_user=delivery_user,
            assigned_by=assigned_by,
            status=DeliveryAssignment.StatusChoices.ASSIGNED,
        )

    @staticmethod
    @transaction.atomic
    def mark_delivered(shipment, pod_data, user):
        if not can_mark_delivered(user, shipment):
            raise ValidationError("You do not have permission to deliver this shipment.")
        if shipment.status not in [Shipment.StatusChoices.RECEIVED, Shipment.StatusChoices.OUT_FOR_DELIVERY]:
            raise ValidationError("Shipment must be received or out for delivery before it can be delivered.")

        shipment.status = Shipment.StatusChoices.DELIVERED
        shipment.save(update_fields=["status", "updated_at", "updated_by"])
        ProofOfDelivery.objects.create(
            shipment=shipment,
            received_by_name=pod_data["received_by_name"],
            received_by_phone=pod_data["received_by_phone"],
            delivery_notes=pod_data.get("delivery_notes"),
            delivered_at=pod_data.get("delivered_at", timezone.now()),
        )
        DeliveryAssignment.objects.filter(
            shipment=shipment,
            delivery_user=user,
            status=DeliveryAssignment.StatusChoices.ASSIGNED,
        ).update(status=DeliveryAssignment.StatusChoices.COMPLETED, completed_at=timezone.now(), updated_at=timezone.now(), updated_by=user)
        ShipmentWorkflowService.record_event(shipment, ShipmentEvent.EventType.DELIVERED, user, office=shipment.destination_office)
        return shipment

    @staticmethod
    @transaction.atomic
    def cancel(shipment, user, notes=None):
        if not can_cancel_shipment(user, shipment):
            raise ValidationError("You do not have permission to cancel this shipment.")
        if shipment.status not in [Shipment.StatusChoices.DRAFT, Shipment.StatusChoices.BOOKED]:
            raise ValidationError(f"Cannot cancel shipment in {shipment.status} status.")
        shipment.status = Shipment.StatusChoices.CANCELLED
        shipment.save(update_fields=["status", "updated_at", "updated_by"])
        ShipmentWorkflowService.record_event(shipment, ShipmentEvent.EventType.CANCELLED, user, office=shipment.origin_office, notes=notes)
        return shipment
