from django.contrib import admin
from .models import Customer, Invoice, InvoiceItem, Expense


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'doctor_name', 'store', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('name', 'phone', 'email', 'doctor_name')
    readonly_fields = ('created_at', 'updated_at')


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    fields = ('medicine_name', 'batch_number', 'expiry_date', 'quantity', 'unit_price', 'tax_percentage', 'tax_amount', 'total_price')
    readonly_fields = ('created_at',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number', 'store', 'customer_name', 'customer_phone',
        'payment_method', 'status', 'total_amount', 'created_by', 'created_at'
    )
    list_filter = ('store', 'status', 'payment_method', 'created_at')
    search_fields = ('invoice_number', 'customer_name', 'customer_phone', 'doctor_name')
    inlines = [InvoiceItemInline]
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Invoice Header', {
            'fields': ('store', 'invoice_number', 'created_by', 'status')
        }),
        ('Customer & Doctor Information', {
            'fields': ('customer', 'customer_name', 'customer_phone', 'doctor_name')
        }),
        ('Payment & Financials', {
            'fields': ('payment_method', 'subtotal', 'tax_amount', 'discount_amount', 'total_amount')
        }),
        ('Additional Information', {
            'fields': ('notes', 'is_active')
        }),
        ('Audit Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'medicine_name', 'batch_number', 'quantity', 'unit_price', 'total_price', 'store')
    list_filter = ('store', 'invoice__status', 'invoice__payment_method')
    search_fields = ('medicine_name', 'batch_number', 'invoice__invoice_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'amount', 'expense_date', 'payment_method', 'paid_to', 'store', 'created_by')
    list_filter = ('store', 'category', 'payment_method', 'expense_date')
    search_fields = ('title', 'paid_to', 'notes')
    readonly_fields = ('created_at', 'updated_at')

