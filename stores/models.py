from django.db import models
from core.models import TimeStampedModel, SoftDeleteModel


class Store(TimeStampedModel, SoftDeleteModel):
    """
    Represents a tenant pharmacy store.
    All business data (inventory, batches, billing, staff) is owned by a Store.
    """
    name = models.CharField(max_length=255, help_text="Pharmacy / Store Name")
    code = models.CharField(max_length=50, unique=True, db_index=True, help_text="Unique Store Code (e.g., PHARM-01)")
    license_number = models.CharField(max_length=100, help_text="Drug License Number")
    gst_number = models.CharField(max_length=50, blank=True, null=True, help_text="GST / Tax Registration Number")
    phone = models.CharField(max_length=20, help_text="Store Contact Phone")
    email = models.EmailField(help_text="Store Contact Email")
    address = models.TextField(help_text="Street address")
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=20)
    currency = models.CharField(max_length=10, default="₹", help_text="Currency symbol or ISO code")
    logo = models.ImageField(upload_to='store_logos/', blank=True, null=True, help_text="Pharmacy Store Logo for Invoices and Branding")
    upi_id = models.CharField(max_length=100, blank=True, null=True, help_text="Store UPI ID / VPA (e.g. merchant@upi, pharmacy@okhdfcbank)")
    upi_payee_name = models.CharField(max_length=255, blank=True, null=True, help_text="Payee Name displayed on customer UPI apps")

    class WhatsAppGatewayType(models.TextChoices):
        DEFAULT = 'default', 'Platform Default'
        OWN = 'own', "Client's Own API Key"

    whatsapp_service_type = models.CharField(
        max_length=20,
        choices=WhatsAppGatewayType.choices,
        default=WhatsAppGatewayType.DEFAULT,
        help_text="WhatsApp Sending Mode: Platform Default or Client's Own API Key"
    )
    whatsapp_api_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Client's custom WABA API Key (used when mode is Client's Own)"
    )

    def get_whatsapp_api_key(self):
        """Returns the appropriate WhatsApp API key based on sending type."""
        if self.whatsapp_service_type == self.WhatsAppGatewayType.OWN and self.whatsapp_api_key:
            return self.whatsapp_api_key.strip()
        from core.models import PlatformSetting
        return PlatformSetting.get_settings().waba_api_key.strip()

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Pharmacy Store"
        verbose_name_plural = "Pharmacy Stores"

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def full_address(self):
        parts = [self.address, self.city, self.state, self.pincode]
        return ", ".join(p for p in parts if p)

    @property
    def upi_display_name(self):
        return self.upi_payee_name.strip() if self.upi_payee_name else self.name
