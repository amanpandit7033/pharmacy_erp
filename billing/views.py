import json
from decimal import Decimal
from django.views.generic import ListView, DetailView, TemplateView, CreateView, UpdateView
from django.views import View
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum, Count
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from billing.models import Invoice, InvoiceItem, Customer, Expense
from billing.forms import ExpenseForm
from billing.services import create_invoice, cancel_invoice, update_invoice
from billing.pdf import generate_invoice_pdf
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
                    'customer_name': request.POST.get('customer_name', 'Customer'),
                    'customer_phone': request.POST.get('customer_phone', ''),
                    'customer_address': request.POST.get('customer_address', ''),
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

    def get_queryset(self):
        return super().get_queryset().select_related('store', 'created_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['items'] = self.object.items.all().select_related('batch', 'batch__medicine')
        context['can_cancel'] = (
            self.request.user.role == User.Role.STORE_ADMIN and
            self.object.status == Invoice.Status.PAID
        )
        return context



class InvoicePDFView(View):
    """
    Renders and serves a binary PDF for the invoice with Content-Type: application/pdf.
    Accessible without session auth so WhatsApp Gateway (waba.azmobia.com) can download media.
    """
    def get(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=pk)
        pdf_bytes = generate_invoice_pdf(invoice)
        filename = f"{invoice.invoice_number}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Content-Length'] = len(pdf_bytes)
        return response


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


class InvoiceEditView(TenantAccessMixin, RoleRequiredMixin, View):
    """
    Allows store admin and staff to edit an existing invoice (correct quantities,
    prices, items, discounts, customer information) with atomic stock recalculation.
    """
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get(self, request, pk, *args, **kwargs):
        store = request.user.store
        invoice = get_object_or_404(Invoice, pk=pk, store=store)

        if invoice.status == Invoice.Status.CANCELLED:
            messages.error(request, "Cancelled / refunded bills cannot be edited.")
            return redirect('billing:invoice_detail', pk=invoice.pk)

        # Build active batches list for POS item search
        # Include quantity held by this invoice for any batches already on the bill
        items_by_batch = {item.batch_id: item.quantity for item in invoice.items.all() if item.batch_id}

        batches = Batch.objects.filter(
            store=store,
            is_active=True,
            status=Batch.Status.ACTIVE,
            expiry_date__gt=timezone.localdate(),
        ).filter(
            Q(quantity__gt=0) | Q(id__in=items_by_batch.keys())
        ).select_related('medicine', 'medicine__unit').order_by('medicine__name', 'expiry_date')

        batch_list = []
        for b in batches:
            held_qty = items_by_batch.get(b.id, 0)
            batch_list.append({
                'id': b.id,
                'medicine_name': b.medicine.name,
                'generic_name': b.medicine.generic_name or '',
                'unit': b.medicine.unit.short_name if b.medicine.unit else 'unit',
                'rack': b.medicine.rack_location or '',
                'batch_number': b.batch_number,
                'expiry_date': b.expiry_date.strftime('%Y-%m-%d'),
                'selling_price': str(b.selling_price),
                'mrp': str(b.mrp),
                'tax_percentage': str(b.tax_percentage),
                'available_qty': b.quantity + held_qty,
            })

        # Pre-populate cart items from existing invoice items
        initial_items = []
        for item in invoice.items.select_related('batch', 'batch__medicine', 'batch__medicine__unit'):
            held_qty = item.quantity
            avail = (item.batch.quantity + held_qty) if item.batch else 999999
            initial_items.append({
                'uid': f"inv_item_{item.id}",
                'batch_id': item.batch_id,
                'medicine_name': item.medicine_name,
                'batch_number': item.batch_number or 'OTC',
                'expiry_date': item.expiry_date.strftime('%Y-%m-%d') if item.expiry_date else '',
                'unit': item.batch.medicine.unit.short_name if item.batch and item.batch.medicine and item.batch.medicine.unit else 'unit',
                'unit_price': float(item.unit_price),
                'tax_percentage': float(item.tax_percentage),
                'available_qty': avail,
                'quantity': item.quantity,
                'is_manual': not bool(item.batch_id)
            })

        context = {
            'is_edit_mode': True,
            'invoice': invoice,
            'initial_cart_json': json.dumps(initial_items),
            'batches_json': json.dumps(batch_list),
            'payment_methods': Invoice.PaymentMethod.choices,
            'store_upi_id': store.upi_id or '',
            'store_upi_payee': store.upi_display_name,
        }
        return render(request, 'billing/pos.html', context)

    def post(self, request, pk, *args, **kwargs):
        store = request.user.store
        invoice = get_object_or_404(Invoice, pk=pk, store=store)

        if invoice.status == Invoice.Status.CANCELLED:
            messages.error(request, "Cancelled bills cannot be edited.")
            return redirect('billing:invoice_detail', pk=invoice.pk)

        try:
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
                    'customer_name': request.POST.get('customer_name', invoice.customer_name),
                    'customer_phone': request.POST.get('customer_phone', ''),
                    'customer_address': request.POST.get('customer_address', ''),
                    'doctor_name': request.POST.get('doctor_name', ''),
                    'payment_method': request.POST.get('payment_method', invoice.payment_method),
                    'discount_amount': discount_val,
                    'notes': request.POST.get('notes', invoice.notes),
                    'items': items_list
                }

            updated = update_invoice(invoice, request.user, payload)
            messages.success(request, f"Invoice #{updated.invoice_number} updated successfully.")

            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'status': 'success',
                    'invoice_id': updated.id,
                    'invoice_number': updated.invoice_number,
                    'redirect_url': reverse('billing:invoice_detail', kwargs={'pk': updated.id})
                })

            return redirect('billing:invoice_detail', pk=updated.id)

        except (ValidationError, Exception) as e:
            err_msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({'status': 'error', 'message': err_msg}, status=400)

            messages.error(request, f"Error updating bill: {err_msg}")
            return redirect('billing:invoice_edit', pk=invoice.pk)


class ExpenseListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    """
    Store Admin view for tracking daily operational expenses.
    Features date filters, category breakdowns, and aggregate financial totals.
    """
    model = Expense
    template_name = 'billing/expense_list.html'
    context_object_name = 'expenses'
    paginate_by = 25
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_queryset(self):
        qs = super().get_queryset().select_related('created_by')
        q = self.request.GET.get('q', '').strip()
        category = self.request.GET.get('category', '').strip()
        payment = self.request.GET.get('payment', '').strip()
        from_date = self.request.GET.get('from_date', '').strip()
        to_date = self.request.GET.get('to_date', '').strip()

        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(paid_to__icontains=q) |
                Q(notes__icontains=q)
            )
        if category:
            qs = qs.filter(category=category)
        if payment:
            qs = qs.filter(payment_method=payment)
        if from_date:
            qs = qs.filter(expense_date__gte=from_date)
        if to_date:
            qs = qs.filter(expense_date__lte=to_date)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store
        today = timezone.localdate()
        month_start = today.replace(day=1)

        store_expenses = Expense.objects.filter(store=store, is_active=True)

        expense_totals = store_expenses.aggregate(
            today_total=Sum('amount', filter=Q(expense_date=today)),
            month_total=Sum('amount', filter=Q(expense_date__gte=month_start, expense_date__lte=today)),
            all_time_total=Sum('amount'),
        )
        today_total = expense_totals['today_total'] or Decimal('0.00')
        month_total = expense_totals['month_total'] or Decimal('0.00')
        all_time_total = expense_totals['all_time_total'] or Decimal('0.00')

        # Filtered queryset total for currently viewed results
        filtered_qs = self.get_queryset()
        filtered_total = filtered_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Category breakdown for this month
        category_breakdown = (
            store_expenses.filter(expense_date__gte=month_start, expense_date__lte=today)
            .values('category')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')[:5]
        )
        cat_display_map = dict(Expense.Category.choices)
        top_categories = []
        for cat in category_breakdown:
            top_categories.append({
                'category_code': cat['category'],
                'category_name': cat_display_map.get(cat['category'], cat['category']),
                'total': cat['total'],
                'count': cat['count'],
            })

        context['today_total'] = today_total
        context['month_total'] = month_total
        context['all_time_total'] = all_time_total
        context['filtered_total'] = filtered_total
        context['top_categories'] = top_categories
        context['categories'] = Expense.Category.choices
        context['payment_methods'] = Expense.PaymentMethod.choices
        return context


class ExpenseCreateView(TenantAccessMixin, RoleRequiredMixin, CreateView):
    """Store Admin creates a new operational daily expense entry."""
    model = Expense
    form_class = ExpenseForm
    template_name = 'billing/expense_form.html'
    allowed_roles = [User.Role.STORE_ADMIN]
    success_url = reverse_lazy('billing:expense_list')

    def form_valid(self, form):
        form.instance.store = self.request.user.store
        form.instance.created_by = self.request.user
        messages.success(self.request, f"Expense '{form.instance.title}' of {self.request.user.store.currency}{form.instance.amount} recorded successfully.")
        return super().form_valid(form)


class ExpenseUpdateView(TenantAccessMixin, RoleRequiredMixin, UpdateView):
    """Store Admin edits an existing operational expense entry."""
    model = Expense
    form_class = ExpenseForm
    template_name = 'billing/expense_form.html'
    allowed_roles = [User.Role.STORE_ADMIN]
    success_url = reverse_lazy('billing:expense_list')

    def form_valid(self, form):
        messages.success(self.request, f"Expense '{form.instance.title}' updated successfully.")
        return super().form_valid(form)


class ExpenseDeleteView(TenantAccessMixin, RoleRequiredMixin, View):
    """Store Admin removes an expense entry."""
    allowed_roles = [User.Role.STORE_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        expense = get_object_or_404(Expense, pk=pk, store=request.user.store)
        title = expense.title
        expense.delete()
        messages.success(request, f"Expense '{title}' deleted successfully.")
        return redirect('billing:expense_list')


class InvoiceWhatsAppSendView(TenantAccessMixin, RoleRequiredMixin, View):
    """Dispatches invoice template message to customer WhatsApp via waba.azmobia.com."""
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def post(self, request, pk, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=pk, store=request.user.store)
        phone = request.POST.get('customer_phone', '').strip()
        if phone:
            invoice.customer_phone = phone
            invoice.save(update_fields=['customer_phone'])

        from billing.whatsapp import send_invoice_whatsapp
        success, message = send_invoice_whatsapp(invoice, request=request)
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
            return JsonResponse({'success': success, 'message': message})
            
        if success:
            messages.success(request, message)
        else:
            messages.warning(request, message)
        return redirect('billing:invoice_detail', pk=pk)

