from django.contrib import admin
from .models import Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'license_number', 'city', 'state', 'phone', 'is_active', 'created_at')
    list_filter = ('is_active', 'state', 'city')
    search_fields = ('name', 'code', 'license_number', 'gst_number', 'phone', 'email')
    list_editable = ('is_active',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Store Identity', {
            'fields': ('name', 'code', 'logo', 'currency', 'is_active')
        }),
        ('Regulatory & Tax', {
            'fields': ('license_number', 'gst_number')
        }),
        ('Contact Information', {
            'fields': ('phone', 'email')
        }),
        ('Location Address', {
            'fields': ('address', 'city', 'state', 'pincode')
        }),
        ('Audit Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    actions = ['hard_delete_selected_stores', 'soft_delete_selected_stores', 'restore_selected_stores']

    def get_queryset(self, request):
        """Show all stores including soft-deleted ones in Django Admin."""
        return Store.all_objects.all()

    def has_delete_permission(self, request, obj=None):
        return True

    def delete_model(self, request, obj):
        """Perform permanent hard-deletion when deleting from Django Admin detail view."""
        obj.hard_delete()

    def delete_queryset(self, request, queryset):
        """Permanently delete selected stores in bulk from Django Admin."""
        count = queryset.count()
        for item in queryset:
            item.hard_delete()
        from django.contrib import messages
        self.message_user(request, f"Permanently deleted {count} pharmacy store(s) and associated tenant records.", messages.SUCCESS)

    @admin.action(description="Permanently delete selected stores (Hard Delete)")
    def hard_delete_selected_stores(self, request, queryset):
        count = queryset.count()
        for item in queryset:
            item.hard_delete()
        from django.contrib import messages
        self.message_user(request, f"Permanently deleted {count} pharmacy store(s) and associated tenant records.", messages.SUCCESS)

    @admin.action(description="Soft delete / Deactivate selected stores")
    def soft_delete_selected_stores(self, request, queryset):
        count = queryset.update(is_active=False)
        from django.contrib import messages
        self.message_user(request, f"Deactivated {count} pharmacy store(s).", messages.SUCCESS)

    @admin.action(description="Restore selected stores (Set Active)")
    def restore_selected_stores(self, request, queryset):
        count = queryset.update(is_active=True)
        from django.contrib import messages
        self.message_user(request, f"Restored {count} pharmacy store(s).", messages.SUCCESS)

