from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import AuditBaseModel


class Shipment(AuditBaseModel):
    class StatusChoices(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        BOOKED = "BOOKED", _("Booked")
        IN_TRANSIT = "IN_TRANSIT", _("In Transit")
        RECEIVED = "RECEIVED", _("Received")
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", _("Out for Delivery")
        DELIVERED = "DELIVERED", _("Delivered")
        CANCELLED = "CANCELLED", _("Cancelled")

    class BasisChoices(models.TextChoices):
        PAID = "PAID", _("Paid")
        TO_PAY = "TO_PAY", _("To Pay")
        TBB = "TBB", _("TBB (To Be Billed)")

    class PaymentTypeChoices(models.TextChoices):
        CASH = "CASH", _("Cash")
        BANK = "BANK", _("Bank/UPI")
        BRANCH = "BRANCH", _("Branch")
        CREDIT = "CREDIT", _("Credit")

    class ModeChoices(models.TextChoices):
        ROAD = "ROAD", _("Road")
        AIR = "AIR", _("Air")
        TRAIN = "TRAIN", _("Train")
        SEA = "SEA", _("Sea")

    class DeliveryTypeChoices(models.TextChoices):
        DOOR = "DOOR", _("Door Delivery")
        OFFICE = "OFFICE", _("Office Collection")

    company = models.ForeignKey("core.Company", related_name="shipments", on_delete=models.CASCADE)
    lr_no = models.CharField(max_length=50)
    date = models.DateField()
    status = models.CharField(max_length=50, choices=StatusChoices.choices, default=StatusChoices.DRAFT)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    idempotency_hash = models.CharField(max_length=64, null=True, blank=True)

    from_city = models.ForeignKey("core.City", related_name="+", on_delete=models.PROTECT)
    origin_office = models.ForeignKey("core.CompanyOffice", related_name="outgoing_shipments", on_delete=models.PROTECT)
    to_city = models.ForeignKey("core.City", related_name="+", on_delete=models.PROTECT)
    destination_office = models.ForeignKey("core.CompanyOffice", related_name="incoming_shipments", on_delete=models.PROTECT)

    basis = models.CharField(max_length=50, choices=BasisChoices.choices, default=BasisChoices.PAID)
    payment_type = models.CharField(max_length=50, choices=PaymentTypeChoices.choices, default=PaymentTypeChoices.CASH)
    mode = models.CharField(max_length=50, choices=ModeChoices.choices, default=ModeChoices.ROAD)
    delivery_type = models.CharField(max_length=50, choices=DeliveryTypeChoices.choices, default=DeliveryTypeChoices.DOOR)

    consignor_name = models.CharField(max_length=100)
    consignor_city = models.ForeignKey("core.City", related_name="+", on_delete=models.PROTECT)
    consignor_phone = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^\d{10}$", _("Phone number must be exactly 10 digits."))],
    )
    consignor_address = models.TextField(blank=True, null=True)

    consignee_name = models.CharField(max_length=100)
    consignee_city = models.ForeignKey("core.City", related_name="+", on_delete=models.PROTECT)
    consignee_phone = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^\d{10}$", _("Phone number must be exactly 10 digits."))],
    )
    consignee_address = models.TextField(blank=True, null=True)

    gst_party = models.CharField(max_length=100, blank=True, null=True)
    gst_number = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$",
                _("Invalid Indian GSTIN format."),
            )
        ],
    )
    notes = models.TextField(blank=True, null=True)

    freight = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    additional_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    final_freight = models.GeneratedField(
        expression=models.F("freight") + models.F("additional_charges") + models.F("delivery_charge"),
        output_field=models.DecimalField(max_digits=10, decimal_places=2),
        db_persist=True,
    )
    advance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    remaining_balance = models.GeneratedField(
        expression=models.F("freight") + models.F("additional_charges") + models.F("delivery_charge") - models.F("advance_amount"),
        output_field=models.DecimalField(max_digits=10, decimal_places=2),
        db_persist=True,
    )

    total_packages = models.PositiveIntegerField(default=0)
    total_actual_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    total_charge_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])

    class Meta:
        ordering = ["-date", "-created_at"]
        permissions = [
            ("view_all_offices", "Can view shipments from all offices"),
            ("add_shipment_all_offices", "Can add shipments for all offices"),
            ("reassign_all_offices", "Can reassign shipment origin/destination to any office"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["company", "idempotency_key"], name="unique_company_shipment_idempotency_key", condition=models.Q(idempotency_key__isnull=False)),
            models.UniqueConstraint(fields=["company", "lr_no"], name="unique_company_lr_no"),
            models.CheckConstraint(condition=models.Q(advance_amount__lte=models.F("freight") + models.F("additional_charges") + models.F("delivery_charge")), name="advance_amount_lte_shipment_final_freight"),
        ]
        indexes = [
            models.Index(fields=["company", "is_active", "-date"], name="idx_shipment_tenant_date"),
            models.Index(fields=["company", "lr_no"], name="idx_tenant_lr_no"),
            models.Index(fields=["origin_office", "is_active"], name="idx_origin_office_active"),
            models.Index(fields=["destination_office", "is_active"], name="idx_dest_office_active"),
            models.Index(fields=["company", "status"], name="idx_shipment_tenant_status"),
            GinIndex(name="shipment_consignor_trgm_idx", fields=["consignor_name"], opclasses=["gin_trgm_ops"]),
            GinIndex(name="shipment_consignee_trgm_idx", fields=["consignee_name"], opclasses=["gin_trgm_ops"]),
        ]

    def save(self, *args, **kwargs):
        if self.idempotency_key == "":
            self.idempotency_key = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.lr_no or f"Shipment {self.pk}"


class ShipmentLineItem(AuditBaseModel):
    class ItemTypeChoices(models.TextChoices):
        GENERAL = "GENERAL", _("General")
        HAZARDOUS = "HAZARDOUS", _("Hazardous")
        PERISHABLE = "PERISHABLE", _("Perishable")
        FRAGILE = "FRAGILE", _("Fragile")

    class PackageTypeChoices(models.TextChoices):
        BOX = "BOX", _("Box")
        BAG = "BAG", _("Bag")
        CRATE = "CRATE", _("Crate")
        BUNDLE = "BUNDLE", _("Bundle")
        PALLET = "PALLET", _("Pallet")

    class RateTypeChoices(models.TextChoices):
        PER_KG = "PER_KG", _("Per Kg")
        PER_PIECE = "PER_PIECE", _("Per Piece")
        FLAT = "FLAT", _("Flat Rate")

    shipment = models.ForeignKey(Shipment, related_name="line_items", on_delete=models.CASCADE)
    item_type = models.CharField(max_length=50, choices=ItemTypeChoices.choices, default=ItemTypeChoices.GENERAL)
    package_type = models.CharField(max_length=50, choices=PackageTypeChoices.choices, default=PackageTypeChoices.BOX)
    rate_type = models.CharField(max_length=50, choices=RateTypeChoices.choices, default=RateTypeChoices.PER_KG)
    pieces = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    actual_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))], default=Decimal("0.00"))
    charged_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))], default=Decimal("0.00"))
    rate = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    charge = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    rate_rule = models.ForeignKey("RateRule", related_name="line_items", on_delete=models.SET_NULL, null=True, blank=True)
    override_reason = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


class ShipmentEvent(AuditBaseModel):
    class EventType(models.TextChoices):
        BOOKED = "BOOKED", _("Booked")
        DISPATCHED = "DISPATCHED", _("Dispatched")
        RECEIVED = "RECEIVED", _("Received")
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", _("Out for Delivery")
        DELIVERED = "DELIVERED", _("Delivered")
        CANCELLED = "CANCELLED", _("Cancelled")

    shipment = models.ForeignKey(Shipment, related_name="events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50, choices=EventType.choices)
    office = models.ForeignKey("core.CompanyOffice", related_name="shipment_events", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="shipment_events", on_delete=models.PROTECT)
    notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["-occurred_at", "-created_at"]
        indexes = [
            models.Index(fields=["shipment", "-occurred_at"], name="idx_shipment_event_time"),
            models.Index(fields=["office", "event_type"], name="idx_event_office_type"),
        ]


class DeliveryAssignment(AuditBaseModel):
    class StatusChoices(models.TextChoices):
        ASSIGNED = "ASSIGNED", _("Assigned")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")

    shipment = models.ForeignKey(Shipment, related_name="delivery_assignments", on_delete=models.CASCADE)
    delivery_user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="assignments", on_delete=models.PROTECT)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="assigned_by", on_delete=models.PROTECT)
    status = models.CharField(max_length=50, choices=StatusChoices.choices, default=StatusChoices.ASSIGNED)
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-assigned_at"]


class ProofOfDelivery(AuditBaseModel):
    shipment = models.OneToOneField(Shipment, related_name="pod", on_delete=models.CASCADE)
    received_by_name = models.CharField(max_length=100)
    received_by_phone = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^\d{10}$", _("Phone number must be exactly 10 digits."))],
    )
    delivery_notes = models.TextField(blank=True, null=True)
    delivered_at = models.DateTimeField()


class RateCard(AuditBaseModel):
    company = models.ForeignKey("core.Company", related_name="rate_cards", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-effective_from"]


class RateRule(AuditBaseModel):
    rate_card = models.ForeignKey(RateCard, related_name="rules", on_delete=models.CASCADE)
    origin_city = models.ForeignKey("core.City", related_name="rate_rules_origin", on_delete=models.CASCADE)
    destination_city = models.ForeignKey("core.City", related_name="rate_rules_destination", on_delete=models.CASCADE)
    origin_office = models.ForeignKey("core.CompanyOffice", related_name="rate_rules_origin", on_delete=models.CASCADE, null=True, blank=True)
    destination_office = models.ForeignKey("core.CompanyOffice", related_name="rate_rules_destination", on_delete=models.CASCADE, null=True, blank=True)
    basis = models.CharField(max_length=50, choices=Shipment.BasisChoices.choices)
    rate_type = models.CharField(max_length=50, choices=ShipmentLineItem.RateTypeChoices.choices)
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    min_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])


class OfficeRatePolicy(AuditBaseModel):
    company = models.ForeignKey("core.Company", related_name="office_rate_policies", on_delete=models.CASCADE)
    office = models.OneToOneField("core.CompanyOffice", related_name="rate_policy", on_delete=models.CASCADE)
    can_override_rate = models.BooleanField(default=False)
    max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    requires_approval = models.BooleanField(default=False)


class ShipmentSequence(models.Model):
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE)
    date = models.DateField()
    last_value = models.IntegerField(default=0)

    class Meta:
        unique_together = ("company", "date")
