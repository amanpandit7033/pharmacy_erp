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
