from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model with created_at and updated_at timestamps."""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """Queryset providing soft delete filtering and operations."""

    def alive(self):
        return self.filter(is_active=True)

    def dead(self):
        return self.filter(is_active=False)

    def delete(self):
        """Soft delete all items in queryset."""
        return self.update(is_active=False)

    def hard_delete(self):
        """Permanently delete all items in queryset."""
        return super().delete()


class SoftDeleteManager(models.Manager):
    """Manager returning active records by default."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def deleted_only(self):
        return SoftDeleteQuerySet(self.model, using=self._db).dead()


class SoftDeleteModel(models.Model):
    """Abstract model supporting soft-deletion via is_active flag."""
    is_active = models.BooleanField(default=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """Soft delete this instance."""
        self.is_active = False
        self.save(update_fields=['is_active'])

    def restore(self):
        """Restore this soft-deleted instance."""
        self.is_active = True
        self.save(update_fields=['is_active'])

    def hard_delete(self):
        """Permanently delete this record from the database."""
        super().delete()


class TenantQuerySet(SoftDeleteQuerySet):
    """QuerySet providing automatic store-level isolation."""

    def for_store(self, store):
        """Filter queryset strictly to the specified store instance or ID."""
        if not store:
            return self.none()
        return self.filter(store=store)


class TenantManager(SoftDeleteManager):
    """Manager ensuring default access is scoped to a store and soft-deleted items are excluded."""

    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db).alive()

    def for_store(self, store):
        return self.get_queryset().for_store(store)


class TenantModel(TimeStampedModel, SoftDeleteModel):
    """
    Abstract base model for all store-owned entities.
    Every store-owned model inherits from this to guarantee:
    1. Direct store FK with proper indexing
    2. Automatic soft delete
    3. Created and updated timestamps
    4. Tenant-scoped manager
    """
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_records",
        db_index=True
    )

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True


class PlatformSetting(TimeStampedModel):
    """
    Platform-wide branding and operational settings (singleton).
    Configurable exclusively by Super Admin.
    """
    brand_name = models.CharField(
        max_length=100,
        default='Azmed',
        help_text="Platform or brand name displayed across the system."
    )
    logo_icon = models.ImageField(
        upload_to='branding/',
        null=True,
        blank=True,
        help_text="1:1 square brand logo icon (PNG, JPG, SVG, WebP)."
    )
    tagline = models.CharField(
        max_length=255,
        default='Expert support for a happier, healthier you.',
        blank=True,
        help_text="Subtitle or tagline displayed on login and public headers."
    )
    footer_text = models.CharField(
        max_length=255,
        default='© 2026 Azmed. All rights reserved.',
        blank=True,
        help_text="Custom copyright or disclaimer text displayed in the login screen footer."
    )
    footer_contact_info = models.CharField(
        max_length=255,
        blank=True,
        default='Need support? Contact IT Desk at support@azmed.com',
        help_text="Optional support info or contact line displayed under the footer text."
    )
    show_login_footer = models.BooleanField(
        default=True,
        help_text="Enable or disable footer visibility on the login page."
    )

    # SMTP / Email Configuration
    smtp_is_enabled = models.BooleanField(
        default=False,
        help_text="Enable automated email dispatch (store invitations, credentials, alerts)."
    )
    smtp_host = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="SMTP server host (e.g., smtp.gmail.com, smtp.office365.com, smtp.sendgrid.net)"
    )
    smtp_port = models.PositiveIntegerField(
        default=587,
        help_text="SMTP server port (typically 587 for TLS or 465 for SSL)"
    )
    smtp_user = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="SMTP account username or sender email address."
    )
    smtp_password = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="SMTP account password or app-specific application password."
    )
    smtp_use_tls = models.BooleanField(
        default=True,
        help_text="Use TLS connection security (Recommended for port 587)."
    )
    smtp_use_ssl = models.BooleanField(
        default=False,
        help_text="Use SSL connection security (Recommended for port 465)."
    )
    smtp_default_from_email = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Sender email appearing in 'From:' field (e.g., Azmed ERP <noreply@azmed.com>)."
    )
    send_welcome_email = models.BooleanField(
        default=True,
        help_text="Automatically send professional onboarding email with login credentials when a store admin is created."
    )

    class Meta:
        verbose_name = 'Platform Setting'
        verbose_name_plural = 'Platform Settings'

    def __str__(self):
        return f"Platform Settings ({self.brand_name})"

    @classmethod
    def get_settings(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create(
                brand_name='Azmed',
                tagline='Expert support for a happier, healthier you.',
                footer_text='© 2026 Azmed. All rights reserved.',
                footer_contact_info='Need support? Contact IT Desk at support@azmed.com',
                show_login_footer=True
            )
        return obj

