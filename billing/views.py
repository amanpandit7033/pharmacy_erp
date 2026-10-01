import json
from decimal import Decimal
from django.views.generic import ListView, DetailView, TemplateView
from django.views import View
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from billing.models import Invoice, InvoiceItem, Customer
from billing.services import create_invoice, cancel_invoice
from inventory.models import Batch, Medicine
from accounts.models import User
from billing.utils import amount_to_words
from core.mixins import RoleRequiredMixin, TenantAccessMixin


class POSView(TenantAccessMixin, RoleRequiredMixin, TemplateView):
    """Interactive point-of-sale terminal for rapid customer billing."""
    template_name = 'billing/pos.html'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store

        # Fetch active, non-quarantined batches with quantity > 0 and not expired for POS item selector
        batches = Batch.objects.filter(
            store=store,
            is_active=True,
            status=Batch.Status.ACTIVE,
            expiry_date__gt=timezone.localdate(),
            quantity__gt=0
        ).select_related('medicine', 'medicine__unit').order_by('medicine__name', 'expiry_date')

        batch_list = []
        for b in batches:
            batch_list.append({
                'id': b.id,
                'medicine_name': b.medicine.name,
                'generic_name': b.medicine.generic_name or '',
                'unit': b.medicine.unit.short_name,
                'rack': b.medicine.rack_location or '',
                'batch_number': b.batch_number,
                'expiry_date': b.expiry_date.strftime('%Y-%m-%d'),
                'selling_price': str(b.selling_price),
                'mrp': str(b.mrp),
                'tax_percentage': str(b.tax_percentage),
                'available_qty': b.quantity,
            })

        context['batches_json'] = json.dumps(batch_list)
        context['payment_methods'] = Invoice.PaymentMethod.choices
        context['store_upi_id'] = store.upi_id or ''
        context['store_upi_payee'] = store.upi_display_name
        return context

    def post(self, request, *args, **kwargs):
        store = request.user.store
        try:
            # Check if JSON payload or form-encoded
            if request.content_type == 'application/json':
                payload = json.loads(request.body)
            else:
                raw_items = request.POST.get('items_json')
                raw_discount = str(request.POST.get('discount_amount') or '0.00').strip()
                items_list = json.loads(raw_items) if raw_items else []

                if raw_discount.endswith('%'):
                    try:
                        pct = Decimal(raw_discount.rstrip('%').strip() or '0')
                        gross = Decimal('0.00')
                        for it in items_list:
                            u_pr = Decimal(str(it.get('unit_price') or '0'))
                            u_qty = Decimal(str(it.get('quantity') or '0'))
                            u_tax = Decimal(str(it.get('tax_percentage') or '0'))
                            line_s = u_pr * u_qty
                            line_t = (line_s * (u_tax / Decimal('100.00'))).quantize(Decimal('0.01'))
                            gross += line_s + line_t
                        discount_val = (gross * (pct / Decimal('100.00'))).quantize(Decimal('0.01'))
                    except Exception:
                        discount_val = Decimal('0.00')
                else:
                    try:
                        discount_val = Decimal(raw_discount)
                    except Exception:
                        discount_val = Decimal('0.00')

                payload = {
                    'customer_name': request.POST.get('customer_name', 'Walk-in Customer'),
                    'customer_phone': request.POST.get('customer_phone', ''),
                    'doctor_name': request.POST.get('doctor_name', ''),
                    'payment_method': request.POST.get('payment_method', Invoice.PaymentMethod.CASH),
                    'discount_amount': discount_val,
                    'notes': request.POST.get('notes', ''),
                    'items': items_list
                }

            invoice = create_invoice(store, request.user, payload)
            messages.success(request, f"Invoice #{invoice.invoice_number} created successfully.")

            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'status': 'success',
                    'invoice_id': invoice.id,
                    'invoice_number': invoice.invoice_number,
                    'redirect_url': reverse('billing:invoice_detail', kwargs={'pk': invoice.id})
                })

            return redirect('billing:invoice_detail', pk=invoice.id)

        except (ValidationError, Exception) as e:
            err_msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'status': 'error', 'message': err_msg}, status=400)

            messages.error(request, f"Billing error: {err_msg}")
            return redirect('billing:pos')


class InvoiceListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    model = Invoice
    template_name = 'billing/invoice_list.html'
    context_object_name = 'invoices'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related('customer', 'created_by')
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        payment = self.request.GET.get('payment', '').strip()
        from_date = self.request.GET.get('from_date', '').strip()
        to_date = self.request.GET.get('to_date', '').strip()
        date = self.request.GET.get('date', '').strip()
        sort = self.request.GET.get('sort', 'latest').strip()

        if q:
            qs = qs.filter(
                Q(invoice_number__icontains=q) |
                Q(customer_name__icontains=q) |
                Q(customer_phone__icontains=q) |
                Q(doctor_name__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if payment:
            qs = qs.filter(payment_method=payment)
        if from_date:
            qs = qs.filter(created_at__date__gte=from_date)
        if to_date:
            qs = qs.filter(created_at__date__lte=to_date)
        if date and not from_date and not to_date:
            qs = qs.filter(created_at__date=date)

        if sort == 'oldest':
            qs = qs.order_by('created_at')
        elif sort == 'amount_high':
            qs = qs.order_by('-total_amount', '-created_at')
        elif sort == 'amount_low':
            qs = qs.order_by('total_amount', '-created_at')
        else:
            qs = qs.order_by('-created_at')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_cancel_bill'] = (self.request.user.role == User.Role.STORE_ADMIN)
        context['payment_methods'] = Invoice.PaymentMethod.choices
        context['status_choices'] = Invoice.Status.choices
        return context


class InvoiceDetailView(TenantAccessMixin, RoleRequiredMixin, DetailView):
    model = Invoice
    template_name = 'billing/invoice_detail.html'
    context_object_name = 'invoice'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = self.object.items.all()
        context['can_cancel'] = (
            self.request.user.role == User.Role.STORE_ADMIN and
            self.object.status == Invoice.Status.PAID
        )
        return context


class InvoicePrintView(TenantAccessMixin, RoleRequiredMixin, DetailView):
    model = Invoice
    template_name = 'billing/invoice_print.html'
    context_object_name = 'invoice'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = list(self.object.items.select_related('batch__medicine__unit').all())
        context['items'] = items
        context['total_quantity'] = sum(item.quantity for item in items)
        
        # Target 10 rows for optimal single-page A4 print fit
        target_rows = 10
        if len(items) < target_rows:
            context['blank_rows'] = range(target_rows - len(items))
        else:
            context['blank_rows'] = []
            
        context['amount_in_words'] = amount_to_words(self.object.total_amount)
        return context


class InvoiceThermalPrintView(TenantAccessMixin, RoleRequiredMixin, DetailView):
    """
    Continuous roll thermal receipt view (80mm standard POS / 58mm compact).
    Optimized for high-contrast thermal printers with zero ink waste, clean monospacing,
    and automatic browser print trigger.
    """
    model = Invoice
    template_name = 'billing/invoice_thermal.html'
    context_object_name = 'invoice'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        items = list(self.object.items.select_related('batch__medicine__unit').all())
        context['items'] = items
        context['total_quantity'] = sum(item.quantity for item in items)
        context['total_items_count'] = len(items)
        context['amount_in_words'] = amount_to_words(self.object.total_amount)
        context['autoprint'] = self.request.GET.get('autoprint', '0') == '1'

        # Calculate GST components (Intra-state CGST 50% + SGST 50%)
        half_tax = (self.object.tax_amount / Decimal('2.0')).quantize(Decimal('0.01'))
        context['cgst_amount'] = half_tax
        context['sgst_amount'] = half_tax

        return context


class InvoiceCancelView(TenantAccessMixin, RoleRequiredMixin, View):
    """Store admin only: Cancels invoice and restores batch stock atomically."""
    allowed_roles = [User.Role.STORE_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=pk, store=request.user.store)
        try:
            cancel_invoice(invoice, request.user)
            messages.success(request, f"Invoice #{invoice.invoice_number} cancelled and stock successfully restored.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect('billing:invoice_detail', pk=invoice.pk)
