from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import TenantModel


class Category(TenantModel):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Manufacturer(TenantModel):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Unit(TenantModel):
    name = models.CharField(max_length=50, help_text="e.g. Strip, Bottle, Box, Vial")
    short_name = models.CharField(max_length=20, help_text="e.g. str, btl, box, ml")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.short_name})"


class Supplier(TenantModel):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gst_number = models.CharField(max_length=30, blank=True, verbose_name="GSTIN / Tax ID")
    dl_number = models.CharField(max_length=50, blank=True, verbose_name="Drug License No.")
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_purchases_amount(self):
        """Total spent on medicines purchased from this supplier."""
        if hasattr(self, 'total_spent') and self.total_spent is not None:
            return self.total_spent
        total = self.batches.filter(is_active=True).aggregate(
            spent=models.Sum(models.F('cost_price') * models.F('quantity'))
        )['spent']
        return total or Decimal('0.00')

    @property
    def total_batches_count(self):
        if hasattr(self, 'batches_count') and self.batches_count is not None:
            return self.batches_count
        return self.batches.filter(is_active=True).count()


class Medicine(TenantModel):
    name = models.CharField(max_length=255, db_index=True)
    generic_name = models.CharField(max_length=255, blank=True, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='medicines')
    manufacturer = models.ForeignKey(Manufacturer, on_delete=models.SET_NULL, null=True, blank=True, related_name='medicines')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='medicines')
    sku = models.CharField(max_length=100, blank=True, help_text="SKU or Barcode")
    rack_location = models.CharField(max_length=100, blank=True, help_text="Rack / Shelf storage location")
    min_stock_level = models.PositiveIntegerField(default=10, help_text="Low stock alert threshold")
    is_prescription_required = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_stock(self):
        """Sum of available quantity in all active and non-quarantined batches."""
        if hasattr(self, 'total_qty') and self.total_qty is not None:
            return self.total_qty
        return self.batches.filter(is_active=True, status=Batch.Status.ACTIVE).aggregate(
            total=models.Sum('quantity')
        )['total'] or 0

    @property
    def is_low_stock(self):
        return self.total_stock <= self.min_stock_level


class Batch(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active / In Stock'
        QUARANTINED = 'QUARANTINED', 'Quarantined (Isolated)'
        DISPOSED = 'DISPOSED', 'Disposed / Written Off'
        RETURNED = 'RETURNED', 'Returned to Supplier'

    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name='batches')
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batches'
    )
    supplier_invoice_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Supplier invoice or bill reference number"
    )
    purchase_date = models.DateField(
        default=timezone.localdate,
        null=True,
        blank=True,
        help_text="Date when batch was procured"
    )
    batch_number = models.CharField(max_length=100, db_index=True)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(db_index=True)
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Purchase cost per unit (Store Admin only - Strictly hidden from staff)"
    )
    mrp = models.DecimalField(max_digits=12, decimal_places=2, help_text="Maximum Retail Price")
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Selling price per unit")
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), help_text="GST/Tax %")
    quantity = models.PositiveIntegerField(default=0, help_text="Available units in stock")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
        help_text="Operational status: Active, Quarantined, Disposed, or Returned"
    )
    quarantine_reason = models.TextField(
        blank=True,
        help_text="Reason for quarantine, write-off, or return"
    )
    quarantined_at = models.DateTimeField(null=True, blank=True)
    quarantined_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='quarantined_batches'
    )

    class Meta:
        ordering = ['expiry_date', 'batch_number']
        verbose_name_plural = "Batches"

    def __str__(self):
        return f"{self.medicine.name} - Batch {self.batch_number} (Qty: {self.quantity})"

    @property
    def is_expired(self):
        return self.expiry_date <= timezone.localdate()

    @property
    def days_until_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_near_expiry(self):
        """Within 60 days of expiry."""
        days = self.days_until_expiry
        return 0 <= days <= 60

    @property
    def is_quarantined(self):
        return self.status == self.Status.QUARANTINED

    @property
    def is_disposed(self):
        return self.status == self.Status.DISPOSED

    @property
    def is_returned(self):
        return self.status == self.Status.RETURNED

    @property
    def is_sellable(self):
        return self.is_active and self.status == self.Status.ACTIVE and not self.is_expired and self.quantity > 0

    def quarantine(self, user=None, reason=''):
        self.status = self.Status.QUARANTINED
        self.quarantine_reason = reason
        self.quarantined_at = timezone.now()
        self.quarantined_by = user
        self.save(update_fields=['status', 'quarantine_reason', 'quarantined_at', 'quarantined_by', 'updated_at'])

    def release_quarantine(self):
        self.status = self.Status.ACTIVE
        self.save(update_fields=['status', 'updated_at'])

    def mark_disposed(self, user=None, reason=''):
        self.status = self.Status.DISPOSED
        if reason:
            self.quarantine_reason = reason
        self.save(update_fields=['status', 'quarantine_reason', 'updated_at'])

    def return_to_supplier(self, user=None, reason=''):
        self.status = self.Status.RETURNED
        if reason:
            self.quarantine_reason = reason
        self.save(update_fields=['status', 'quarantine_reason', 'updated_at'])


class MasterMedicine(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Baseline MRP")
    is_discontinued = models.BooleanField(default=False)
    manufacturer_name = models.CharField(max_length=255, blank=True, db_index=True)
    category_name = models.CharField(max_length=100, blank=True, help_text="e.g. allopathy, ayurvedic, homeopathy")
    pack_size_label = models.CharField(max_length=150, blank=True, help_text="e.g. strip of 10 tablets, bottle of 100 ml")
    short_composition1 = models.CharField(max_length=255, blank=True)
    short_composition2 = models.CharField(max_length=255, blank=True)
    salt_composition = models.TextField(blank=True, db_index=True)
    medicine_desc = models.TextField(blank=True)
    side_effects = models.TextField(blank=True)
    drug_interactions = models.TextField(blank=True)
    is_approved = models.BooleanField(default=True, db_index=True)
    submission_status = models.CharField(
        max_length=20,
        default='approved',
        choices=[
            ('approved', 'Approved'),
            ('pending', 'Pending Approval'),
            ('rejected', 'Rejected'),
        ],
        db_index=True
    )
    submitted_by_store = models.ForeignKey(
        'stores.Store',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='master_contributions'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Master Medicine"
        verbose_name_plural = "Master Medicines"

    def __str__(self):
        return f"{self.name} ({self.pack_size_label})"


