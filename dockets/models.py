from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import RegexValidator, MinValueValidator
from django.utils.translation import gettext_lazy as _
from django.contrib.postgres.indexes import GinIndex
from core.models import AuditBaseModel, generate_ulid


class Docket(AuditBaseModel):
    class StatusChoices(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        BOOKED = 'BOOKED', _('Booked')
        IN_TRANSIT = 'IN_TRANSIT', _('In Transit')
        DELIVERED = 'DELIVERED', _('Delivered')
        CANCELLED = 'CANCELLED', _('Cancelled')
        INCOMING = 'INCOMING', _('Incoming')

    class BasisChoices(models.TextChoices):
        WEIGHT = 'WEIGHT', _('Weight')
        FIXED = 'FIXED', _('Fixed')
        UNIT = 'UNIT', _('Unit')

    class PaymentTypeChoices(models.TextChoices):
        PAID = 'PAID', _('Paid')
        TO_PAY = 'TO_PAY', _('To Pay')
        TBB = 'TBB', _('TBB (To Be Billed)')

    class ModeChoices(models.TextChoices):
        ROAD = 'ROAD', _('Road')
        AIR = 'AIR', _('Air')
        TRAIN = 'TRAIN', _('Train')
        SEA = 'SEA', _('Sea')

    class DeliveryTypeChoices(models.TextChoices):
        DOOR = 'DOOR', _('Door Delivery')
        OFFICE = 'OFFICE', _('Office Collection')

    # Core Information
    company = models.ForeignKey('core.Company', related_name='dockets', on_delete=models.CASCADE)
    docket_no = models.CharField(max_length=50)
    date = models.DateField()
    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        default=StatusChoices.DRAFT
    )
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    idempotency_hash = models.CharField(max_length=64, null=True, blank=True)
    from_city = models.ForeignKey('core.City', related_name='+', on_delete=models.PROTECT)
    origin_branch = models.ForeignKey('core.Branch', related_name='outgoing_dockets', on_delete=models.PROTECT)
    to_city = models.ForeignKey('core.City', related_name='+', on_delete=models.PROTECT)
    destination_branch = models.ForeignKey('core.Branch', related_name='incoming_dockets', on_delete=models.PROTECT)
    basis = models.CharField(
        max_length=50, 
        choices=BasisChoices.choices, 
        default=BasisChoices.WEIGHT
    )
    payment_type = models.CharField(
        max_length=50, 
        choices=PaymentTypeChoices.choices, 
        default=PaymentTypeChoices.PAID
    )
    mode = models.CharField(
        max_length=50, 
        choices=ModeChoices.choices, 
        default=ModeChoices.ROAD
    )
    delivery_type = models.CharField(
        max_length=50, 
        choices=DeliveryTypeChoices.choices, 
        default=DeliveryTypeChoices.DOOR
    )

    # Consignor Information
    consignor_name = models.CharField(max_length=100)
    consignor_city = models.ForeignKey('core.City', related_name='+', on_delete=models.PROTECT)
    consignor_phone = models.CharField(
        max_length=10, 
        validators=[RegexValidator(r'^\d{10}$', _('Phone number must be exactly 10 digits.'))]
    )
    consignor_address = models.TextField(blank=True, null=True)

    # Consignee Information
    consignee_name = models.CharField(max_length=100)
    consignee_city = models.ForeignKey('core.City', related_name='+', on_delete=models.PROTECT)
    consignee_phone = models.CharField(
        max_length=10, 
        validators=[RegexValidator(r'^\d{10}$', _('Phone number must be exactly 10 digits.'))]
    )
    consignee_address = models.TextField(blank=True, null=True)

    # Billing and Notes
    gst_party = models.CharField(max_length=100, blank=True, null=True)
    gst_number = models.CharField(
        max_length=15, 
        blank=True, 
        null=True,
        validators=[
            RegexValidator(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$', _('Invalid Indian GSTIN format.'))
        ]
    )
    notes = models.TextField(blank=True, null=True)

    # Financial and Summary
    freight = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    additional_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    final_freight = models.GeneratedField(
        expression=models.F('freight') + models.F('additional_charges') + models.F('delivery_charge'),
        output_field=models.DecimalField(max_digits=10, decimal_places=2),
        db_persist=True,
    )
    advance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    remaining_balance = models.GeneratedField(
        expression=models.F('freight') + models.F('additional_charges') + models.F('delivery_charge') - models.F('advance_amount'),
        output_field=models.DecimalField(max_digits=10, decimal_places=2),
        db_persist=True,
    )

    total_packages = models.PositiveIntegerField(default=0)
    total_actual_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    total_charge_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = _('Docket')
        verbose_name_plural = _('Dockets')
        permissions = [
            ("view_all_branches", "Can view dockets from all branches"),
            ("add_docket_all_branches", "Can add dockets for all branches"),
            ("reassign_all_branches", "Can reassign docket origin/destination to any branch"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'idempotency_key'], 
                name='unique_company_idempotency_key',
                condition=models.Q(idempotency_key__isnull=False)
            ),
            models.UniqueConstraint(fields=['company', 'docket_no'], name='unique_company_docket_no'),
            models.CheckConstraint(condition=models.Q(freight__gte=0), name='freight_gte_0'),
            models.CheckConstraint(condition=models.Q(additional_charges__gte=0), name='additional_charges_gte_0'),
            models.CheckConstraint(condition=models.Q(delivery_charge__gte=0), name='delivery_charge_gte_0'),
            models.CheckConstraint(condition=models.Q(advance_amount__gte=0), name='advance_amount_gte_0'),
            models.CheckConstraint(condition=models.Q(total_actual_weight__gte=0), name='total_actual_weight_gte_0'),
            models.CheckConstraint(condition=models.Q(total_charge_weight__gte=0), name='total_charge_weight_gte_0'),
            models.CheckConstraint(condition=models.Q(final_freight__gte=0), name='final_freight_gte_0'),
            models.CheckConstraint(
                condition=models.Q(
                    advance_amount__lte=(models.F('freight') + models.F('additional_charges') + models.F('delivery_charge'))
                ), 
                name='advance_amount_lte_final_freight'
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'is_active', '-date'], name='idx_tenant_active_date'),
            models.Index(fields=['company', 'docket_no'], name='idx_tenant_docket_no'),
            models.Index(fields=['origin_branch', 'is_active'], name='idx_origin_active'),
            models.Index(fields=['destination_branch', 'is_active'], name='idx_dest_active'),
            models.Index(fields=['company', 'status'], name='idx_tenant_status'),
            GinIndex(
                name='consignor_name_trgm_idx', 
                fields=['consignor_name'], 
                opclasses=['gin_trgm_ops']
            ),
            GinIndex(
                name='consignee_name_trgm_idx', 
                fields=['consignee_name'], 
                opclasses=['gin_trgm_ops']
            ),
        ]

    @property
    def calculated_total_pieces(self):
        return sum(item.pieces for item in self.line_items.all())

    @property
    def calculated_total_actual_weight(self):
        return sum(item.actual_weight for item in self.line_items.all())

    @property
    def calculated_total_charge_weight(self):
        return sum(item.charged_weight for item in self.line_items.all())

    @property
    def calculated_line_item_charge_total(self):
        return sum(item.charge for item in self.line_items.all())

    def __str__(self):
        return self.docket_no or f'Docket {self.pk}'

    def save(self, *args, **kwargs):
        # Normalize "" to None to ensure unique constraints on idempotency_key (which allow 
        # multiple NULLs but only one "") are respected, even for non-API creations.
        if self.idempotency_key == "":
            self.idempotency_key = None
        super().save(*args, **kwargs)


class DocketLineItem(AuditBaseModel):
    class ItemTypeChoices(models.TextChoices):
        GENERAL = 'GENERAL', _('General')
        HAZARDOUS = 'HAZARDOUS', _('Hazardous')
        PERISHABLE = 'PERISHABLE', _('Perishable')
        FRAGILE = 'FRAGILE', _('Fragile')

    class PackageTypeChoices(models.TextChoices):
        BOX = 'BOX', _('Box')
        BAG = 'BAG', _('Bag')
        CRATE = 'CRATE', _('Crate')
        BUNDLE = 'BUNDLE', _('Bundle')
        PALLET = 'PALLET', _('Pallet')

    class RateTypeChoices(models.TextChoices):
        PER_KG = 'PER_KG', _('Per Kg')
        PER_PIECE = 'PER_PIECE', _('Per Piece')
        FLAT = 'FLAT', _('Flat Rate')

    docket = models.ForeignKey(Docket, related_name='line_items', on_delete=models.CASCADE)
    
    item_type = models.CharField(
        max_length=50, 
        choices=ItemTypeChoices.choices, 
        default=ItemTypeChoices.GENERAL
    )
    package_type = models.CharField(
        max_length=50, 
        choices=PackageTypeChoices.choices, 
        default=PackageTypeChoices.BOX
    )
    rate_type = models.CharField(
        max_length=50, 
        choices=RateTypeChoices.choices, 
        default=RateTypeChoices.PER_KG
    )
    pieces = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    actual_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))], default=Decimal('0.00'))
    charged_weight = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))], default=Decimal('0.00'))
    rate = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    charge = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    
    # Rate management fields
    rate_rule = models.ForeignKey('RateRule', related_name='line_items', on_delete=models.SET_NULL, null=True, blank=True)
    override_reason = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name = _('Docket Line Item')
        verbose_name_plural = _('Docket Line Items')
        ordering = ['id']
        constraints = [
            models.CheckConstraint(condition=models.Q(rate__gte=0), name='rate_gte_0'),
            models.CheckConstraint(condition=models.Q(charge__gte=0), name='charge_gte_0'),
            models.CheckConstraint(condition=models.Q(pieces__gte=1), name='pieces_gte_1'),
        ]

    def __str__(self):
        return f'{self.pieces} {self.package_type} of {self.item_type} for {self.docket}'


class RateCard(AuditBaseModel):
    company = models.ForeignKey('core.Company', related_name='rate_cards', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-effective_from']
        verbose_name = _('Rate Card')
        verbose_name_plural = _('Rate Cards')

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class RateRule(AuditBaseModel):
    rate_card = models.ForeignKey(RateCard, related_name='rules', on_delete=models.CASCADE)
    origin_city = models.ForeignKey('core.City', related_name='rate_rules_origin', on_delete=models.CASCADE)
    destination_city = models.ForeignKey('core.City', related_name='rate_rules_destination', on_delete=models.CASCADE)
    origin_branch = models.ForeignKey('core.Branch', related_name='rate_rules_origin', on_delete=models.CASCADE, null=True, blank=True)
    destination_branch = models.ForeignKey('core.Branch', related_name='rate_rules_destination', on_delete=models.CASCADE, null=True, blank=True)
    basis = models.CharField(max_length=50, choices=Docket.BasisChoices.choices)
    rate_type = models.CharField(max_length=50, choices=DocketLineItem.RateTypeChoices.choices)
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    min_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        verbose_name = _('Rate Rule')
        verbose_name_plural = _('Rate Rules')

    def __str__(self):
        return f"{self.origin_city} to {self.destination_city} - {self.rate_card.name}"


class BranchRatePolicy(AuditBaseModel):
    company = models.ForeignKey('core.Company', related_name='branch_rate_policies', on_delete=models.CASCADE)
    branch = models.OneToOneField('core.Branch', related_name='rate_policy', on_delete=models.CASCADE)
    can_override_rate = models.BooleanField(default=False)
    max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    requires_approval = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('Branch Rate Policy')
        verbose_name_plural = _('Branch Rate Policies')

    def __str__(self):
        return f"Rate Policy for {self.branch.name}"


class DocketSequence(models.Model):
    company = models.ForeignKey('core.Company', on_delete=models.CASCADE)
    date = models.DateField()
    last_value = models.IntegerField(default=0)

    class Meta:
        verbose_name = _('Docket Sequence')
        verbose_name_plural = _('Docket Sequences')
        unique_together = ('company', 'date')


class DocketStatusEvent(AuditBaseModel):
    docket = models.ForeignKey(Docket, related_name='status_events', on_delete=models.CASCADE)
    from_status = models.CharField(max_length=50, choices=Docket.StatusChoices.choices)
    to_status = models.CharField(max_length=50, choices=Docket.StatusChoices.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Docket Status Event')
        verbose_name_plural = _('Docket Status Events')


class DeliveryAssignment(AuditBaseModel):
    class StatusChoices(models.TextChoices):
        ASSIGNED = 'ASSIGNED', _('Assigned')
        COMPLETED = 'COMPLETED', _('Completed')
        CANCELLED = 'CANCELLED', _('Cancelled')

    docket = models.ForeignKey(Docket, related_name='delivery_assignments', on_delete=models.CASCADE)
    delivery_user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='assignments', on_delete=models.PROTECT)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='assigned_by', on_delete=models.PROTECT)
    status = models.CharField(max_length=50, choices=StatusChoices.choices, default=StatusChoices.ASSIGNED)
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-assigned_at']
        verbose_name = _('Delivery Assignment')
        verbose_name_plural = _('Delivery Assignments')


class ProofOfDelivery(AuditBaseModel):
    docket = models.OneToOneField(Docket, related_name='pod', on_delete=models.CASCADE)
    received_by_name = models.CharField(max_length=100)
    received_by_phone = models.CharField(
        max_length=10, 
        validators=[RegexValidator(r'^\d{10}$', _('Phone number must be exactly 10 digits.'))]
    )
    delivery_notes = models.TextField(blank=True, null=True)
    delivered_at = models.DateTimeField()

    class Meta:
        verbose_name = _('Proof of Delivery')
        verbose_name_plural = _('Proofs of Delivery')
