from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from rest_framework import serializers
from core.request_context import get_current_branch, get_current_company
from .models import Docket, DocketLineItem, DocketStatusEvent, DeliveryAssignment, ProofOfDelivery
from .tasks import send_status_update_notification
from .services import lookup_rate, get_branch_rate_policy

class ProofOfDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProofOfDelivery
        fields = ['received_by_name', 'received_by_phone', 'delivery_notes', 'delivered_at']

class DocketStatusEventSerializer(serializers.ModelSerializer):
    changed_by_name = serializers.ReadOnlyField(source='changed_by.username')
    branch_name = serializers.ReadOnlyField(source='branch.name')

    class Meta:
        model = DocketStatusEvent
        fields = ['id', 'from_status', 'to_status', 'changed_by', 'changed_by_name', 'branch', 'branch_name', 'notes', 'created_at']

class DeliveryAssignmentSerializer(serializers.ModelSerializer):
    delivery_user_name = serializers.ReadOnlyField(source='delivery_user.username')
    assigned_by_name = serializers.ReadOnlyField(source='assigned_by.username')

    class Meta:
        model = DeliveryAssignment
        fields = ['id', 'delivery_user', 'delivery_user_name', 'assigned_by', 'assigned_by_name', 'status', 'assigned_at', 'completed_at']

class DocketLineItemSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False)

    class Meta:
        model = DocketLineItem
        fields = [
            'id', 'item_type', 'package_type', 'rate_type', 
            'pieces', 'actual_weight', 'charged_weight', 'rate', 'charge',
            'rate_rule', 'override_reason'
        ]
        read_only_fields = ['rate_rule']

    def validate(self, data):
        # Merge data with instance for partial updates (PATCH)
        # attrs in validate only contains fields provided in the request for partial updates.
        instance = self.instance
        if not instance and 'id' in data:
            instance = self.context.get('line_item_instances_by_id', {}).get(data['id'])
        
        def get_val(field_name, default):
            if field_name in data:
                return data[field_name]
            if instance and hasattr(instance, field_name):
                return getattr(instance, field_name)
            return default

        rate_type = get_val('rate_type', DocketLineItem.RateTypeChoices.PER_KG)
        pieces = get_val('pieces', 0)
        charged_weight = get_val('charged_weight', Decimal('0.00'))
        rate = get_val('rate', Decimal('0.00'))

        if rate_type == DocketLineItem.RateTypeChoices.PER_PIECE:
            data['charge'] = (rate * pieces).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif rate_type == DocketLineItem.RateTypeChoices.PER_KG:
            data['charge'] = (rate * charged_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif rate_type == DocketLineItem.RateTypeChoices.FLAT:
            data['charge'] = rate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        return data

class DocketListSerializer(serializers.ModelSerializer):
    origin_branch_name = serializers.ReadOnlyField(source='origin_branch.name')
    destination_branch_name = serializers.ReadOnlyField(source='destination_branch.name')
    to_city_name = serializers.ReadOnlyField(source='to_city.name')
    total_amount = serializers.ReadOnlyField(source='final_freight')
    assigned_delivery_user = serializers.SerializerMethodField()
    latest_status_event_timestamp = serializers.SerializerMethodField()

    class Meta:
        model = Docket
        fields = [
            'id', 'docket_no', 'date', 'status',
            'origin_branch_name', 'destination_branch_name',
            'to_city_name',
            'consignor_name', 'consignee_name',
            'total_packages', 'final_freight', 'total_amount',
            'remaining_balance', 'payment_type', 'delivery_type',
            'assigned_delivery_user', 'latest_status_event_timestamp'
        ]

    def get_assigned_delivery_user(self, obj):
        assignment = obj.delivery_assignments.filter(status='ASSIGNED').first()
        return assignment.delivery_user.username if assignment else None

    def get_latest_status_event_timestamp(self, obj):
        event = obj.status_events.order_by('-created_at').first()
        return event.created_at if event else None

class DocketSerializer(serializers.ModelSerializer):
    date = serializers.DateField(input_formats=['%d/%m/%Y', '%Y-%m-%d'])
    created_by_name = serializers.ReadOnlyField(source='created_by.username')
    updated_by_name = serializers.ReadOnlyField(source='updated_by.username')
    company_name = serializers.ReadOnlyField(source='company.name')
    origin_branch_name = serializers.ReadOnlyField(source='origin_branch.name')
    destination_branch_name = serializers.ReadOnlyField(source='destination_branch.name')
    line_items = DocketLineItemSerializer(many=True)
    status_events = DocketStatusEventSerializer(many=True, read_only=True)
    delivery_assignments = DeliveryAssignmentSerializer(many=True, read_only=True)
    assigned_delivery_user = serializers.SerializerMethodField()
    latest_status_event_timestamp = serializers.SerializerMethodField()

    class Meta:
        model = Docket
        fields = [
            'id', 'company', 'company_name', 'docket_no', 'idempotency_key', 'date', 'status', 'from_city', 
            'origin_branch', 'origin_branch_name', 
            'to_city', 'destination_branch', 'destination_branch_name', 
            'basis', 'payment_type', 
            'mode', 'delivery_type', 'consignor_name', 'consignor_city', 
            'consignor_phone', 'consignor_address', 'consignee_name', 
            'consignee_city', 'consignee_phone', 'consignee_address', 
            'gst_party', 'gst_number', 'notes', 
            'freight', 'additional_charges', 'delivery_charge', 
            'final_freight', 'advance_amount', 'remaining_balance', 
            'total_packages', 'total_actual_weight', 'total_charge_weight', 
            'line_items', 'status_events', 'delivery_assignments',
            'assigned_delivery_user', 'latest_status_event_timestamp',
            'created_at', 'updated_at', 'created_by', 'updated_by',
            'created_by_name', 'updated_by_name'
        ]
        read_only_fields = [
            'docket_no', 'final_freight', 'remaining_balance', 
            'created_at', 'updated_at', 
            'created_by', 'updated_by', 'company',
            'freight', 'total_packages', 'total_actual_weight', 'total_charge_weight'
        ]

    def get_assigned_delivery_user(self, obj):
        assignment = obj.delivery_assignments.filter(status='ASSIGNED').first()
        return assignment.delivery_user.username if assignment else None

    def get_latest_status_event_timestamp(self, obj):
        event = obj.status_events.order_by('-created_at').first()
        return event.created_at if event else None

    def to_internal_value(self, data):
        data = data.copy()

        if self.instance:
            self.context['line_item_instances_by_id'] = {
                item.id: item for item in self.instance.line_items.all()
            }
        else:
            self.context.pop('line_item_instances_by_id', None)

        if not self.instance:
            request = self.context.get('request')
            user = getattr(request, 'user', None)

            # If origin_branch is not provided, use the selected active branch.
            if 'origin_branch' not in data and user:
                branch = get_current_branch()
                if branch:
                    data['origin_branch'] = branch.id
                    if branch.city_id:
                        data['from_city'] = branch.city_id
            
            # If from_city is not provided but origin_branch is, infer it
            if 'from_city' not in data and 'origin_branch' in data:
                from core.models import Branch
                try:
                    branch = Branch.objects.get(pk=data['origin_branch'])
                    if branch.city_id:
                        data['from_city'] = branch.city_id
                except Branch.DoesNotExist:
                    pass

        # Normalize fields before field-level validation
        if 'gst_number' in data and data['gst_number']:
            data['gst_number'] = str(data['gst_number']).upper().strip()
        if 'consignor_phone' in data and data['consignor_phone']:
            data['consignor_phone'] = str(data['consignor_phone']).strip().replace(" ", "")
        if 'consignee_phone' in data and data['consignee_phone']:
            data['consignee_phone'] = str(data['consignee_phone']).strip().replace(" ", "")
        if 'idempotency_key' in data and data['idempotency_key'] == "":
            data['idempotency_key'] = None
            
        return super().to_internal_value(data)

    def validate(self, data):
        request = self.context.get('request')
        if not request or not request.user:
            return data
            
        company = get_current_company()
        user = request.user
        origin_branch = data.get('origin_branch')
        dest_branch = data.get('destination_branch')

        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})

        # Resolve fields for validation against instance for partial updates
        resolved_origin_branch = origin_branch or getattr(self.instance, 'origin_branch', None)
        resolved_dest_branch = dest_branch or getattr(self.instance, 'destination_branch', None)
        resolved_from_city = data.get('from_city', getattr(self.instance, 'from_city', None))
        resolved_to_city = data.get('to_city', getattr(self.instance, 'to_city', None))

        if resolved_origin_branch and resolved_from_city and resolved_origin_branch.city != resolved_from_city:
            raise serializers.ValidationError({"from_city": "from_city must match the origin_branch city."})
            
        if resolved_dest_branch and resolved_to_city and resolved_dest_branch.city != resolved_to_city:
            raise serializers.ValidationError({"to_city": "to_city must match the destination_branch city."})

        line_items_data = data.get('line_items')
        if line_items_data is not None:
            line_item_ids = [item.get('id') for item in line_items_data if item.get('id')]
            if not self.instance and line_item_ids:
                raise serializers.ValidationError({
                    "line_items": "Line item IDs are not accepted when creating a docket."
                })

            if self.instance:
                existing_ids = set(self.context.get('line_item_instances_by_id', {}).keys())
                unknown_ids = [item_id for item_id in line_item_ids if item_id not in existing_ids]
                if unknown_ids:
                    raise serializers.ValidationError({
                        "line_items": f"Line item with ID {unknown_ids[0]} does not exist on this docket."
                    })

        if origin_branch:
            if origin_branch.company != company:
                raise serializers.ValidationError({"origin_branch": "This branch does not belong to your company."})
            if not origin_branch.is_active:
                raise serializers.ValidationError({"origin_branch": "Origin branch is not active."})
                
        if dest_branch:
            if dest_branch.company != company:
                raise serializers.ValidationError({"destination_branch": "This branch does not belong to your company."})
            if not dest_branch.is_active:
                raise serializers.ValidationError({"destination_branch": "Destination branch is not active."})

        if resolved_origin_branch and resolved_origin_branch.company != company:
            raise serializers.ValidationError({"origin_branch": "This branch does not belong to your company."})
        if resolved_dest_branch and resolved_dest_branch.company != company:
            raise serializers.ValidationError({"destination_branch": "This branch does not belong to your company."})

        # Branch Authorization Check
        from core.policies import has_role, can_create_docket, can_edit_docket
        from core.models import Role

        if not user.is_superuser and not has_role(user, roles=[Role.PLATFORM_ADMIN]):
            if not self.instance:
                # Creating a new docket
                resolved_origin = origin_branch or getattr(self.instance, 'origin_branch', None)
                if not resolved_origin:
                     raise serializers.ValidationError({"origin_branch": "Origin branch is required."})
                
                can_create = can_create_docket(user, resolved_origin)
                
                if not can_create:
                    raise serializers.ValidationError({"origin_branch": "You do not have permission to create dockets for this origin branch."})
            else:
                # Updating an existing docket
                if not can_edit_docket(user, self.instance):
                    raise serializers.ValidationError({"detail": "You do not have permission to update this docket."})
                
                # Check if they are trying to reassign origin branch and they don't have permission for the new one
                if origin_branch and origin_branch != self.instance.origin_branch:
                    if not can_create_docket(user, origin_branch):
                        raise serializers.ValidationError({
                            "origin_branch": "You do not have permission to assign to this origin branch."
                        })

        # Status Transition Logic
        if self.instance and 'status' in data:
            old_status = self.instance.status
            new_status = data['status']
            
            # Define allowed paths
            ALLOWED_TRANSITIONS = {
                'DRAFT': ['BOOKED', 'CANCELLED'],
                'BOOKED': ['IN_TRANSIT', 'CANCELLED'],
                'IN_TRANSIT': ['INCOMING', 'DELIVERED'],
                'INCOMING': ['DELIVERED'],
                'DELIVERED': [], # Terminal state
                'CANCELLED': []  # Terminal state
            }
            
            if new_status != old_status and new_status not in ALLOWED_TRANSITIONS.get(old_status, []):
                raise serializers.ValidationError({
                    "status": f"Invalid transition. Cannot change status from {old_status} to {new_status}."
                })

        # Rate Validation
        if resolved_origin_branch and resolved_dest_branch:
            basis = data.get('basis', getattr(self.instance, 'basis', Docket.BasisChoices.WEIGHT))
            policy = get_branch_rate_policy(company, resolved_origin_branch)
            rule = lookup_rate(company, resolved_origin_branch, resolved_dest_branch, basis)
            
            if line_items_data:
                for item_data in line_items_data:
                    # Resolve rate_type from data or instance
                    item_instance = None
                    if self.instance and item_data.get('id'):
                        item_instance = self.context.get('line_item_instances_by_id', {}).get(item_data['id'])
                    
                    rate_type = item_data.get('rate_type', getattr(item_instance, 'rate_type', DocketLineItem.RateTypeChoices.PER_KG))
                    
                    if rule:
                        # Store rule ID in a temporary field for create/update to handle
                        item_data['_rate_rule_id'] = rule.id
                        
                        standard_rate = rule.rate
                        submitted_rate = item_data.get('rate')
                        
                        # If rate not provided in partial update, it's not being changed
                        if submitted_rate is None and item_instance:
                            submitted_rate = item_instance.rate

                        if submitted_rate is not None and submitted_rate != standard_rate:
                            # Super admins and Platform admins can override anything
                            from core.models import Role
                            if not user.is_superuser and not has_role(user, roles=[Role.PLATFORM_ADMIN]):
                                if not policy.can_override_rate:
                                    raise serializers.ValidationError({
                                        "line_items": f"Branch {resolved_origin_branch.name} is not allowed to override rates."
                                    })
                                
                                # Check discount limit
                                if standard_rate > 0:
                                    discount = ((standard_rate - submitted_rate) / standard_rate) * 100
                                    if discount > policy.max_discount_percent:
                                        raise serializers.ValidationError({
                                            "line_items": f"Rate override exceeds maximum allowed discount of {policy.max_discount_percent}%."
                                        })
                                
                                if not item_data.get('override_reason') and not getattr(item_instance, 'override_reason', None):
                                    raise serializers.ValidationError({
                                        "line_items": "Override reason is required when manual rate override is used."
                                    })

        return data

    @transaction.atomic
    def create(self, validated_data):
        line_items_data = validated_data.pop('line_items', [])
        
        if not line_items_data:
            raise serializers.ValidationError({"line_items": "At least one line item is required."})
            
        # Calculate derived fields for validation and initial save
        freight = sum(item.get('charge', Decimal('0.00')) for item in line_items_data)
        additional = validated_data.get('additional_charges', Decimal('0.00'))
        delivery = validated_data.get('delivery_charge', Decimal('0.00'))
        final_freight = freight + additional + delivery
        
        # Catch Advance > Freight cleanly
        advance = validated_data.get('advance_amount', Decimal('0.00'))
        if advance > final_freight:
            raise serializers.ValidationError({
                "advance_amount": f"Advance amount ({advance}) cannot exceed final freight ({final_freight})."
            })

        # Set totals on validated_data before creating Docket to satisfy DB constraints
        validated_data['freight'] = freight
        validated_data['total_packages'] = sum(item.get('pieces', 0) for item in line_items_data)
        validated_data['total_actual_weight'] = sum(item.get('actual_weight', Decimal('0.00')) for item in line_items_data)
        validated_data['total_charge_weight'] = sum(item.get('charged_weight', Decimal('0.00')) for item in line_items_data)

        docket = Docket.objects.create(**validated_data)
        
        # Explicitly set audit fields for nested line items if available in validated_data
        created_by = validated_data.get('created_by')
        updated_by = validated_data.get('updated_by')
        
        for item_data in line_items_data:
            if created_by:
                item_data['created_by'] = created_by
            if updated_by:
                item_data['updated_by'] = updated_by
            
            rate_rule_id = item_data.pop('_rate_rule_id', None)
            if rate_rule_id:
                item_data['rate_rule_id'] = rate_rule_id
                
            DocketLineItem.objects.create(docket=docket, **item_data)

        # Recalculate totals from the saved DB objects
        docket.refresh_from_db()
        docket.freight = docket.calculated_line_item_charge_total
        docket.total_packages = docket.calculated_total_pieces
        docket.total_actual_weight = docket.calculated_total_actual_weight
        docket.total_charge_weight = docket.calculated_total_charge_weight
        docket.save(update_fields=['freight', 'total_packages', 'total_actual_weight', 'total_charge_weight'])
        
        return docket

    @transaction.atomic
    def update(self, instance, validated_data):
        # Lock the instance for the duration of the transaction
        instance = Docket.objects.select_for_update().get(pk=instance.pk)
        
        # Re-verify status transition with locked record to prevent race conditions
        status_changed = False
        old_status_val = None
        new_status_val = None
        
        if 'status' in validated_data:
            old_status = instance.status
            new_status = validated_data['status']
            if old_status != new_status:
                status_changed = True
                old_status_val = old_status
                new_status_val = new_status
                ALLOWED_TRANSITIONS = {
                    'DRAFT': ['BOOKED', 'CANCELLED'],
                    'BOOKED': ['IN_TRANSIT', 'CANCELLED'],
                    'IN_TRANSIT': ['INCOMING', 'DELIVERED'],
                    'INCOMING': ['DELIVERED'],
                    'DELIVERED': [],
                    'CANCELLED': []
                }
                if new_status not in ALLOWED_TRANSITIONS.get(old_status, []):
                    raise serializers.ValidationError({
                        "status": f"Invalid transition from {old_status} to {new_status}. The record may have been modified by another user."
                    })

        line_items_data = validated_data.pop('line_items', None)
        
        # Update main docket fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Recalculate for advance validation if either charges or advance changed
        if line_items_data is not None:
            # When line_items are provided, we treat it as a full replacement of the list
            # regardless of whether it's PUT or PATCH. This is more intuitive for Dockets.
            new_freight = sum(item.get('charge', Decimal('0.00')) for item in line_items_data)
            instance.freight = new_freight

        final_freight = instance.freight + instance.additional_charges + instance.delivery_charge
        if instance.advance_amount > final_freight:
             raise serializers.ValidationError({
                "advance_amount": f"Advance amount ({instance.advance_amount}) cannot exceed final freight ({final_freight})."
            })

        instance.save()

        # Surgical Update of line items if provided
        if line_items_data is not None:
            item_mapping = {item.id: item for item in instance.line_items.all()}
            data_mapping = {item.get('id'): item for item in line_items_data if item.get('id')}

            # 1. Delete items not in data_mapping (Full replacement)
            for item_id, item in item_mapping.items():
                if item_id not in data_mapping:
                    item.delete()

            # 2. Update existing items and create new ones
            updated_by = validated_data.get('updated_by')
            for item_data in line_items_data:
                item_id = item_data.get('id')
                rate_rule_id = item_data.pop('_rate_rule_id', None)
                
                if item_id:
                    if item_id in item_mapping:
                        # Update existing item
                        item = item_mapping[item_id]
                        for attr, value in item_data.items():
                            if attr != 'id':
                                setattr(item, attr, value)
                        
                        if rate_rule_id:
                            item.rate_rule_id = rate_rule_id
                            
                        if updated_by:
                            item.updated_by = updated_by
                        item.save()
                    else:
                        # Reject unknown ID
                        raise serializers.ValidationError({
                            "line_items": f"Line item with ID {item_id} does not exist on this docket."
                        })
                else:
                    # Create new item
                    if updated_by:
                        item_data['created_by'] = updated_by
                        item_data['updated_by'] = updated_by
                    
                    if rate_rule_id:
                        item_data['rate_rule_id'] = rate_rule_id
                        
                    DocketLineItem.objects.create(docket=instance, **item_data)
            
            # Recalculate totals directly from the saved DB objects
            instance.refresh_from_db()
            instance.freight = instance.calculated_line_item_charge_total
            instance.total_packages = instance.calculated_total_pieces
            instance.total_actual_weight = instance.calculated_total_actual_weight
            instance.total_charge_weight = instance.calculated_total_charge_weight
            
            # Final check for advance vs freight after recalculation
            final_freight = instance.freight + instance.additional_charges + instance.delivery_charge
            if instance.advance_amount > final_freight:
                 raise serializers.ValidationError({
                    "advance_amount": f"Advance amount ({instance.advance_amount}) cannot exceed final freight ({final_freight})."
                })

            instance.save(update_fields=['freight', 'total_packages', 'total_actual_weight', 'total_charge_weight'])
                
        if status_changed:
            transaction.on_commit(
                lambda: send_status_update_notification.delay(instance.id, old_status_val, new_status_val)
            )

        return instance
