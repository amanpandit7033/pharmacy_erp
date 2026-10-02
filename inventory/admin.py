from django.contrib import admin
from .models import Category, Manufacturer, Unit, Supplier, Medicine, Batch, MasterMedicine


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'contact_person', 'phone', 'email', 'gst_number', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'contact_person', 'phone', 'email', 'gst_number', 'dl_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'description', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'contact_person', 'phone', 'email', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'contact_person', 'phone', 'email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'store', 'is_active')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'short_name')
    readonly_fields = ('created_at', 'updated_at')


class BatchInline(admin.TabularInline):
    model = Batch
    extra = 0
    fields = ('batch_number', 'expiry_date', 'cost_price', 'mrp', 'selling_price', 'quantity', 'status')
    readonly_fields = ('created_at',)
    show_change_link = True


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'generic_name', 'store', 'category', 'manufacturer',
        'unit', 'sku', 'rack_location', 'get_total_stock', 'min_stock_level', 'is_active'
    )
    list_filter = ('store', 'is_active', 'is_prescription_required', 'category', 'manufacturer')
    search_fields = ('name', 'generic_name', 'sku', 'rack_location')
    inlines = [BatchInline]
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Total Stock')
    def get_total_stock(self, obj):
        return obj.total_stock


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = (
        'batch_number', 'medicine', 'store', 'quantity', 'cost_price',
        'mrp', 'selling_price', 'expiry_date', 'status', 'is_active'
    )
    list_filter = ('store', 'status', 'is_active', 'expiry_date')
    search_fields = ('batch_number', 'medicine__name', 'medicine__generic_name')
    readonly_fields = ('created_at', 'updated_at', 'quarantined_at')
    fieldsets = (
        ('Batch Identification', {
            'fields': ('store', 'medicine', 'batch_number', 'status', 'is_active')
        }),
        ('Dates', {
            'fields': ('manufacturing_date', 'expiry_date')
        }),
        ('Stock & Pricing', {
            'fields': ('quantity', 'cost_price', 'mrp', 'selling_price', 'tax_percentage')
        }),
        ('Quarantine & Disposal Details', {
            'fields': ('quarantine_reason', 'quarantined_by', 'quarantined_at'),
            'classes': ('collapse',)
        }),
        ('Audit Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(MasterMedicine)
class MasterMedicineAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'manufacturer_name', 'category_name', 'price',
        'pack_size_label', 'is_approved', 'submission_status', 'submitted_by_store', 'created_at'
    )
    list_filter = ('is_approved', 'submission_status', 'is_discontinued', 'category_name')
    search_fields = ('name', 'salt_composition', 'manufacturer_name')
    readonly_fields = ('created_at',)
