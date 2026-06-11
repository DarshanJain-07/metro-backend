from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from core.policies import (
    can_assign_delivery,
    can_cancel_shipment,
    can_dispatch_shipment,
    can_edit_shipment,
    can_mark_delivered,
    can_receive_shipment,
)
from core.request_context import get_current_company, get_current_office
from .models import DeliveryAssignment, ProofOfDelivery, Shipment, ShipmentEvent, ShipmentLineItem
from .services import get_office_rate_policy, lookup_rate


def get_available_shipment_actions(user, shipment):
    if not user or not user.is_authenticated:
        return []

    office = get_current_office()
    actions = []
    if can_edit_shipment(user, shipment):
        actions.append("shipment:update")
    is_closed = shipment.status in [
        Shipment.StatusChoices.DELIVERED,
        Shipment.StatusChoices.CANCELLED,
    ]
    if not is_closed and can_dispatch_shipment(user, shipment):
        actions.append("shipment:dispatch")
    if (
        office
        and shipment.status in [Shipment.StatusChoices.IN_TRANSIT, Shipment.StatusChoices.BOOKED]
        and can_receive_shipment(user, shipment, office)
    ):
        actions.append("shipment:receive")
    if shipment.status == Shipment.StatusChoices.RECEIVED and can_assign_delivery(user, shipment):
        actions.append("shipment:assign_delivery")
    if (
        shipment.status in [Shipment.StatusChoices.RECEIVED, Shipment.StatusChoices.OUT_FOR_DELIVERY]
        and can_mark_delivered(user, shipment)
    ):
        actions.append("shipment:deliver")
    if shipment.status in [Shipment.StatusChoices.DRAFT, Shipment.StatusChoices.BOOKED] and can_cancel_shipment(user, shipment):
        actions.append("shipment:cancel")
    return actions


class ProofOfDeliverySerializer(serializers.ModelSerializer):
    delivered_at = serializers.DateTimeField(required=False)

    class Meta:
        model = ProofOfDelivery
        fields = ["received_by_name", "received_by_phone", "delivery_notes", "delivered_at"]


class ShipmentEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.ReadOnlyField(source="actor.username")
    office_name = serializers.ReadOnlyField(source="office.name")

    class Meta:
        model = ShipmentEvent
        fields = ["id", "event_type", "office", "office_name", "actor", "actor_name", "notes", "metadata", "occurred_at", "created_at"]
        read_only_fields = fields


class DeliveryAssignmentSerializer(serializers.ModelSerializer):
    delivery_user_name = serializers.ReadOnlyField(source="delivery_user.username")
    assigned_by_name = serializers.ReadOnlyField(source="assigned_by.username")

    class Meta:
        model = DeliveryAssignment
        fields = ["id", "delivery_user", "delivery_user_name", "assigned_by", "assigned_by_name", "status", "assigned_at", "completed_at"]


class ShipmentLineItemSerializer(serializers.ModelSerializer):
    id = serializers.CharField(required=False)

    class Meta:
        model = ShipmentLineItem
        fields = [
            "id",
            "item_type",
            "package_type",
            "rate_type",
            "pieces",
            "actual_weight",
            "charged_weight",
            "rate",
            "charge",
            "rate_rule",
            "override_reason",
        ]
        read_only_fields = ["rate_rule"]

    def validate(self, data):
        instance = self.instance
        if not instance and "id" in data:
            instance = self.context.get("line_item_instances_by_id", {}).get(data["id"])

        def get_val(field_name, default):
            if field_name in data:
                return data[field_name]
            if instance and hasattr(instance, field_name):
                return getattr(instance, field_name)
            return default

        rate_type = get_val("rate_type", ShipmentLineItem.RateTypeChoices.PER_KG)
        pieces = get_val("pieces", 0)
        charged_weight = get_val("charged_weight", Decimal("0.00"))
        rate = get_val("rate", Decimal("0.00"))
        if rate_type == ShipmentLineItem.RateTypeChoices.PER_PIECE:
            data["charge"] = (rate * pieces).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif rate_type == ShipmentLineItem.RateTypeChoices.PER_KG:
            data["charge"] = (rate * charged_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif rate_type == ShipmentLineItem.RateTypeChoices.FLAT:
            data["charge"] = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return data


class ShipmentListSerializer(serializers.ModelSerializer):
    docket_no = serializers.ReadOnlyField(source="lr_no")
    origin_office_name = serializers.ReadOnlyField(source="origin_office.name")
    destination_office_name = serializers.ReadOnlyField(source="destination_office.name")
    to_city_name = serializers.ReadOnlyField(source="to_city.name")
    total_amount = serializers.ReadOnlyField(source="final_freight")
    is_billed = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    latest_event_timestamp = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = [
            "id",
            "lr_no",
            "docket_no",
            "date",
            "status",
            "origin_office",
            "origin_office_name",
            "destination_office_name",
            "to_city_name",
            "consignor_name",
            "consignee_name",
            "total_packages",
            "final_freight",
            "total_amount",
            "remaining_balance",
            "basis",
            "payment_type",
            "is_billed",
            "payment_status",
            "delivery_type",
            "latest_event_timestamp",
            "available_actions",
        ]

    def get_is_billed(self, obj):
        return obj.invoice_lines.exists()

    def get_payment_status(self, obj):
        if obj.basis == Shipment.BasisChoices.PAID:
            return "PAID"
        if obj.advance_amount > 0:
            return "PARTIAL"
        return "UNPAID"

    def get_latest_event_timestamp(self, obj):
        event = obj.events.order_by("-occurred_at").first()
        return event.occurred_at if event else None

    def get_available_actions(self, obj):
        request = self.context.get("request")
        return get_available_shipment_actions(getattr(request, "user", None), obj)


class ShipmentSerializer(serializers.ModelSerializer):
    date = serializers.DateField(input_formats=["%d/%m/%Y", "%Y-%m-%d"])
    company_name = serializers.ReadOnlyField(source="company.name")
    origin_office_name = serializers.ReadOnlyField(source="origin_office.name")
    destination_office_name = serializers.ReadOnlyField(source="destination_office.name")
    line_items = ShipmentLineItemSerializer(many=True)
    events = ShipmentEventSerializer(many=True, read_only=True)
    delivery_assignments = DeliveryAssignmentSerializer(many=True, read_only=True)
    available_actions = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = [
            "id",
            "company",
            "company_name",
            "lr_no",
            "idempotency_key",
            "date",
            "status",
            "from_city",
            "origin_office",
            "origin_office_name",
            "to_city",
            "destination_office",
            "destination_office_name",
            "basis",
            "payment_type",
            "mode",
            "delivery_type",
            "consignor_name",
            "consignor_city",
            "consignor_phone",
            "consignor_address",
            "consignee_name",
            "consignee_city",
            "consignee_phone",
            "consignee_address",
            "gst_party",
            "gst_number",
            "notes",
            "freight",
            "additional_charges",
            "delivery_charge",
            "final_freight",
            "advance_amount",
            "remaining_balance",
            "total_packages",
            "total_actual_weight",
            "total_charge_weight",
            "line_items",
            "events",
            "delivery_assignments",
            "available_actions",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = [
            "lr_no",
            "company",
            "freight",
            "final_freight",
            "remaining_balance",
            "total_packages",
            "total_actual_weight",
            "total_charge_weight",
            "available_actions",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]

    def get_available_actions(self, obj):
        request = self.context.get("request")
        return get_available_shipment_actions(getattr(request, "user", None), obj)

    def to_internal_value(self, data):
        data = data.copy()
        if self.instance:
            self.context["line_item_instances_by_id"] = {item.id: item for item in self.instance.line_items.all()}
        else:
            self.context.pop("line_item_instances_by_id", None)
            if "origin_office" not in data:
                office = get_current_office()
                if office:
                    data["origin_office"] = office.id
                    if office.city_id:
                        data["from_city"] = office.city_id
        if "gst_number" in data and data["gst_number"]:
            data["gst_number"] = str(data["gst_number"]).upper().strip()
        for phone_field in ["consignor_phone", "consignee_phone"]:
            if phone_field in data and data[phone_field]:
                data[phone_field] = str(data[phone_field]).strip().replace(" ", "")
        if data.get("idempotency_key") == "":
            data["idempotency_key"] = None
        return super().to_internal_value(data)

    def validate(self, data):
        request = self.context.get("request")
        company = get_current_company()
        if not company:
            raise serializers.ValidationError({"company": "Active company context required."})

        origin_office = data.get("origin_office")
        destination_office = data.get("destination_office")
        resolved_origin = origin_office or getattr(self.instance, "origin_office", None)
        resolved_destination = destination_office or getattr(self.instance, "destination_office", None)
        resolved_from_city = data.get("from_city", getattr(self.instance, "from_city", None))
        resolved_to_city = data.get("to_city", getattr(self.instance, "to_city", None))

        for field, office in [("origin_office", resolved_origin), ("destination_office", resolved_destination)]:
            if office and office.company != company:
                raise serializers.ValidationError({field: "Office does not belong to the active company office master."})

        if resolved_origin and resolved_from_city and resolved_origin.city != resolved_from_city:
            raise serializers.ValidationError({"from_city": "from_city must match the origin office city."})
        if resolved_destination and resolved_to_city and resolved_destination.city != resolved_to_city:
            raise serializers.ValidationError({"to_city": "to_city must match the destination office city."})

        line_items_data = data.get("line_items")
        if line_items_data is not None:
            line_item_ids = [item.get("id") for item in line_items_data if item.get("id")]
            if not self.instance and line_item_ids:
                raise serializers.ValidationError({"line_items": "Line item IDs are not accepted when creating a shipment."})
            if self.instance:
                existing_ids = set(self.context.get("line_item_instances_by_id", {}).keys())
                unknown_ids = [item_id for item_id in line_item_ids if item_id not in existing_ids]
                if unknown_ids:
                    raise serializers.ValidationError({"line_items": f"Line item with ID {unknown_ids[0]} does not exist on this shipment."})

        from core.policies import can_create_shipment, can_edit_shipment

        user = getattr(request, "user", None)
        if user and not user.is_superuser:
            if not self.instance:
                if not resolved_origin:
                    raise serializers.ValidationError({"origin_office": "Origin office is required."})
                if not can_create_shipment(user, resolved_origin):
                    raise serializers.ValidationError({"origin_office": "You do not have permission to create shipments for this office."})
            elif not can_edit_shipment(user, self.instance):
                raise serializers.ValidationError({"detail": "You do not have permission to update this shipment."})

        if resolved_origin and resolved_destination and line_items_data:
            basis = data.get("basis", getattr(self.instance, "basis", Shipment.BasisChoices.PAID))
            policy = get_office_rate_policy(company, resolved_origin)
            rule = lookup_rate(company, resolved_origin, resolved_destination, basis)
            if rule:
                for item_data in line_items_data:
                    item_data["_rate_rule_id"] = rule.id
                    submitted_rate = item_data.get("rate")
                    if submitted_rate is not None and submitted_rate != rule.rate and not policy.can_override_rate:
                        raise serializers.ValidationError({"line_items": f"Office {resolved_origin.name} is not allowed to override rates."})

        return data

    def create(self, validated_data):
        line_items_data = validated_data.pop("line_items", [])
        validated_data["freight"] = sum((item["charge"] for item in line_items_data), Decimal("0.00"))
        validated_data["total_packages"] = sum(item["pieces"] for item in line_items_data)
        validated_data["total_actual_weight"] = sum((item["actual_weight"] for item in line_items_data), Decimal("0.00"))
        validated_data["total_charge_weight"] = sum((item["charged_weight"] for item in line_items_data), Decimal("0.00"))
        shipment = Shipment.objects.create(**validated_data)
        self._save_line_items(shipment, line_items_data)
        self._update_totals(shipment)
        return shipment

    def update(self, instance, validated_data):
        line_items_data = validated_data.pop("line_items", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if line_items_data is not None:
            instance.line_items.all().delete()
            self._save_line_items(instance, line_items_data)
            self._update_totals(instance)
        return instance

    def _save_line_items(self, shipment, line_items_data):
        for item_data in line_items_data:
            item_data.pop("id", None)
            rate_rule_id = item_data.pop("_rate_rule_id", None)
            if rate_rule_id:
                item_data["rate_rule_id"] = rate_rule_id
            ShipmentLineItem.objects.create(shipment=shipment, **item_data)

    def _update_totals(self, shipment):
        items = list(shipment.line_items.all())
        shipment.freight = sum((item.charge for item in items), Decimal("0.00"))
        shipment.total_packages = sum(item.pieces for item in items)
        shipment.total_actual_weight = sum((item.actual_weight for item in items), Decimal("0.00"))
        shipment.total_charge_weight = sum((item.charged_weight for item in items), Decimal("0.00"))
        shipment.save(update_fields=["freight", "total_packages", "total_actual_weight", "total_charge_weight", "updated_at", "updated_by"])
