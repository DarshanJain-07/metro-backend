from decimal import Decimal
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError
from core.request_context import get_current_branch
from .models import (
    Docket, DocketStatusEvent, DeliveryAssignment, 
    ProofOfDelivery, RateCard, RateRule, BranchRatePolicy
)

def get_branch_rate_policy(company, branch):
    """
    Retrieves the rate policy for a specific branch. 
    Creates a default policy if one doesn't exist.
    """
    policy, created = BranchRatePolicy.objects.get_or_create(
        company=company,
        branch=branch,
        defaults={
            'can_override_rate': False,
            'max_discount_percent': Decimal('0.00')
        }
    )
    return policy

def lookup_rate(company, origin_branch, destination_branch, basis):
    """
    Finds the most specific active rate rule for a given route and basis.
    Specificy order:
    1. Branch to Branch
    2. Branch to City (Destination)
    3. City (Origin) to Branch
    4. City to City
    """
    now = timezone.now()
    
    # 1. Find all active rate cards for this company
    active_cards = RateCard.objects.filter(
        company=company,
        is_active=True,
        effective_from__lte=now
    ).filter(
        models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=now)
    ).order_by('-is_default', '-effective_from')

    if not active_cards.exists():
        return None

    # 2. Iterate through cards (starting with default/most recent)
    for card in active_cards:
        rules = RateRule.objects.filter(
            rate_card=card,
            is_active=True,
            basis=basis
        )

        # Priority 1: Exact Branch to Branch
        rule = rules.filter(
            origin_branch=origin_branch,
            destination_branch=destination_branch
        ).first()
        if rule: return rule

        # Priority 2: Origin Branch to Destination City
        rule = rules.filter(
            origin_branch=origin_branch,
            destination_city=destination_branch.city,
            destination_branch__isnull=True
        ).first()
        if rule: return rule

        # Priority 3: Origin City to Destination Branch
        rule = rules.filter(
            origin_city=origin_branch.city,
            destination_branch=destination_branch,
            origin_branch__isnull=True
        ).first()
        if rule: return rule

        # Priority 4: City to City
        rule = rules.filter(
            origin_city=origin_branch.city,
            destination_city=destination_branch.city,
            origin_branch__isnull=True,
            destination_branch__isnull=True
        ).first()
        if rule: return rule

    return None

class DocketWorkflowService:
    @staticmethod
    @transaction.atomic
    def record_status_event(docket, from_status, to_status, user, notes=None):
        return DocketStatusEvent.objects.create(
            docket=docket,
            from_status=from_status,
            to_status=to_status,
            changed_by=user,
            branch=get_current_branch(user),
            notes=notes
        )

    @staticmethod
    @transaction.atomic
    def book_docket(docket, user):
        if docket.status != Docket.StatusChoices.DRAFT:
            raise ValidationError(f"Cannot book docket in {docket.status} status.")
        
        old_status = docket.status
        docket.status = Docket.StatusChoices.BOOKED
        docket.save(update_fields=['status', 'updated_at', 'updated_by'])
        
        DocketWorkflowService.record_status_event(docket, old_status, docket.status, user)
        return docket

    @staticmethod
    @transaction.atomic
    def mark_in_transit(docket, user):
        if docket.status != Docket.StatusChoices.BOOKED:
            raise ValidationError(f"Cannot mark in-transit from {docket.status} status.")
        
        old_status = docket.status
        docket.status = Docket.StatusChoices.IN_TRANSIT
        docket.save(update_fields=['status', 'updated_at', 'updated_by'])
        
        DocketWorkflowService.record_status_event(docket, old_status, docket.status, user)
        return docket

    @staticmethod
    @transaction.atomic
    def receive_docket(docket, user):
        # Can receive from IN_TRANSIT
        if docket.status != Docket.StatusChoices.IN_TRANSIT:
            raise ValidationError(f"Cannot receive docket from {docket.status} status.")
        
        # Verify user branch is destination branch
        if get_current_branch(user) != docket.destination_branch:
             raise ValidationError("Only destination branch can receive this docket.")

        old_status = docket.status
        docket.status = Docket.StatusChoices.INCOMING
        docket.save(update_fields=['status', 'updated_at', 'updated_by'])
        
        DocketWorkflowService.record_status_event(docket, old_status, docket.status, user)
        return docket

    @staticmethod
    @transaction.atomic
    def assign_delivery(docket, delivery_user, assigned_by):
        if docket.status not in [Docket.StatusChoices.INCOMING, Docket.StatusChoices.BOOKED]:
             # Allow assignment from BOOKED if it's direct delivery? 
             # Requirement says DRAFT -> BOOKED -> IN_TRANSIT -> INCOMING -> DELIVERED
             # But INCOMING is destination branch received.
             # If it's DOOR delivery, it should probably be INCOMING first.
             # However, let's stick to the flow or allow INCOMING.
             if docket.status != Docket.StatusChoices.INCOMING:
                 raise ValidationError("Docket must be in INCOMING status to assign delivery.")

        # Cancel previous active assignments if any
        DeliveryAssignment.objects.filter(docket=docket, status=DeliveryAssignment.StatusChoices.ASSIGNED).update(
            status=DeliveryAssignment.StatusChoices.CANCELLED,
            updated_at=timezone.now(),
            updated_by=assigned_by
        )

        return DeliveryAssignment.objects.create(
            docket=docket,
            delivery_user=delivery_user,
            assigned_by=assigned_by,
            status=DeliveryAssignment.StatusChoices.ASSIGNED
        )

    @staticmethod
    @transaction.atomic
    def mark_delivered(docket, pod_data, user):
        if docket.status != Docket.StatusChoices.INCOMING:
            # Maybe it can be delivered directly if it's same branch?
            # Requirement: DRAFT -> BOOKED -> IN_TRANSIT -> INCOMING -> DELIVERED
            if docket.status != Docket.StatusChoices.INCOMING:
                 raise ValidationError("Docket must be in INCOMING status to be marked delivered.")

        old_status = docket.status
        docket.status = Docket.StatusChoices.DELIVERED
        docket.save(update_fields=['status', 'updated_at', 'updated_by'])

        ProofOfDelivery.objects.create(
            docket=docket,
            received_by_name=pod_data['received_by_name'],
            received_by_phone=pod_data['received_by_phone'],
            delivery_notes=pod_data.get('delivery_notes'),
            delivered_at=pod_data.get('delivered_at', timezone.now())
        )

        # Update assignment to completed
        DeliveryAssignment.objects.filter(
            docket=docket, 
            delivery_user=user, 
            status=DeliveryAssignment.StatusChoices.ASSIGNED
        ).update(
            status=DeliveryAssignment.StatusChoices.COMPLETED,
            completed_at=timezone.now(),
            updated_at=timezone.now(),
            updated_by=user
        )

        DocketWorkflowService.record_status_event(docket, old_status, docket.status, user)
        return docket

    @staticmethod
    @transaction.atomic
    def cancel_docket(docket, user, notes=None):
        if docket.status not in [Docket.StatusChoices.DRAFT, Docket.StatusChoices.BOOKED]:
            raise ValidationError(f"Cannot cancel docket in {docket.status} status.")

        old_status = docket.status
        docket.status = Docket.StatusChoices.CANCELLED
        docket.save(update_fields=['status', 'updated_at', 'updated_by'])
        
        DocketWorkflowService.record_status_event(docket, old_status, docket.status, user, notes=notes)
        return docket
