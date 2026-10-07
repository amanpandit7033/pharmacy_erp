from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from core.models import TenantModel


class Customer(TenantModel):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(blank=True)
    doctor_name = models.CharField(max_length=255, blank=True, help_text="Prescribing Doctor Name")
    address = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Invoice(TenantModel):
    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UPI = 'UPI', 'UPI / QR'
        CARD = 'CARD', 'Credit / Debit Card'
        CREDIT = 'CREDIT', 'Store Credit / Due'

    class Status(models.TextChoices):
        PAID = 'PAID', 'Paid'
        CANCELLED = 'CANCELLED', 'Cancelled / Refunded'

    invoice_number = models.CharField(max_length=64, db_index=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
    )
    customer_name = models.CharField(max_length=255, help_text="Walk-in or registered customer name")
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_address = models.TextField(blank=True, default='')
    doctor_name = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_invoices'
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PAID
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [['store', 'invoice_number']]

    def __str__(self):
        return f"Invoice #{self.invoice_number} - {self.customer_name} ({self.store.currency}{self.total_amount})"


class InvoiceItem(TenantModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    batch = models.ForeignKey('inventory.Batch', on_delete=models.SET_NULL, null=True, blank=True, related_name='invoice_items')
    medicine_name = models.CharField(max_length=255)
    batch_number = models.CharField(max_length=100, blank=True, default='')
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.medicine_name} x {self.quantity} on {self.invoice.invoice_number}"

    @property
    def unit_name(self):
        if self.batch and self.batch.medicine and self.batch.medicine.unit:
            return self.batch.medicine.unit.short_name or self.batch.medicine.unit.name or "Unit"
        return "Unit"

    @property
    def generic_name(self):
        if self.batch and self.batch.medicine:
            return self.batch.medicine.generic_name or ""
        return ""


class Expense(TenantModel):
    class Category(models.TextChoices):
        RENT = 'RENT', 'Store Rent'
        SALARY = 'SALARY', 'Staff Salary / Wages'
        ELECTRICITY = 'ELECTRICITY', 'Electricity Bill'
        UTILITIES = 'UTILITIES', 'Utilities & Water'
        TEA_SNACKS = 'TEA_SNACKS', 'Tea & Refreshments'
        PACKAGING = 'PACKAGING', 'Bags & Packaging Materials'
        STATIONERY = 'STATIONERY', 'Stationery & Printing'
        MAINTENANCE = 'MAINTENANCE', 'Repairs & Maintenance'
        TRANSPORT = 'TRANSPORT', 'Freight & Transport'
        MARKETING = 'MARKETING', 'Marketing & Promotion'
        SOFTWARE = 'SOFTWARE', 'Software & Internet'
        MISC = 'MISC', 'Miscellaneous / Other'

    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UPI = 'UPI', 'UPI / QR'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer / NEFT'
        CARD = 'CARD', 'Credit / Debit Card'
        CHEQUE = 'CHEQUE', 'Cheque'

    category = models.CharField(max_length=30, choices=Category.choices, default=Category.MISC, db_index=True)
    title = models.CharField(max_length=200, help_text="Short description of the expense")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField(default=timezone.localdate, db_index=True)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_to = models.CharField(max_length=150, blank=True, help_text="Vendor, employee, or payee")
    receipt = models.FileField(upload_to='expenses/receipts/', blank=True, null=True, help_text="Optional bill or receipt copy")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='logged_expenses'
    )

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_category_display()}) - {self.amount}"

