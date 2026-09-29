from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError


class User(AbstractUser):
    """
    Custom user model supporting multi-tenant role isolation.
    """
    class Role(models.TextChoices):
        SUPER_ADMIN = 'super_admin', 'Super Admin'
        STORE_ADMIN = 'store_admin', 'Store Admin'
        STAFF = 'staff', 'Staff'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
        db_index=True,
        help_text="Role determining user access permissions."
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users',
        help_text="Assigned pharmacy store (Required for store_admin and staff; must be null for super_admin)."
    )
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Contact phone number")

    class Meta:
        ordering = ['username']
        verbose_name = "User"
        verbose_name_plural = "Users"

    def clean(self):
        super().clean()
        # Super admin must not be tied to a specific store (role isolation)
        if self.role == self.Role.SUPER_ADMIN and self.store is not None:
            raise ValidationError({'store': "Super admins cannot be assigned to a specific store."})
        
        # Store admin and staff must be attached to a store
        if self.role in [self.Role.STORE_ADMIN, self.Role.STAFF] and not self.is_superuser:
            if not self.store:
                raise ValidationError({'store': "Store admin and staff members must be assigned to a store."})

    def save(self, *args, **kwargs):
        # Auto-grant superuser/staff flags for django admin if super_admin
        if self.role == self.Role.SUPER_ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)

    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER_ADMIN or self.is_superuser

    @property
    def is_store_admin(self):
        return self.role == self.Role.STORE_ADMIN

    @property
    def is_staff_member(self):
        return self.role == self.Role.STAFF

    @property
    def display_name(self):
        full = self.get_full_name()
        return full if full else self.username

    def __str__(self):
        role_label = self.get_role_display()
        store_str = f" [{self.store.code}]" if self.store else ""
        return f"{self.username} ({role_label}){store_str}"
