from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from billing.models import Invoice, InvoiceItem, Customer
from inventory.models import Batch


def generate_invoice_number(store):
    """
    Generates clean sequential invoice number per store:
    Format: {store.code}-INV-{0001}
    Example: APL01-INV-0001
    """
    prefix = f"{store.code}-INV-"
    last_invoice = Invoice.all_objects.filter(
        store=store,
        invoice_number__startswith=prefix
    ).order_by('-id').first()

    if last_invoice:
        try:
            last_seq = int(last_invoice.invoice_number.split('-')[-1])
            new_seq = last_seq + 1
        except (ValueError, IndexError):
            new_seq = 1
    else:
        new_seq = 1

    return f"{prefix}{new_seq:04d}"


@transaction.atomic
def create_invoice(store, user, data):
    """
    Creates an invoice and decrements stock in active batches atomically.
    data format:
    {
        'customer_name': str,
        'customer_phone': str,
        'doctor_name': str,
        'payment_method': str,
        'discount_amount': Decimal,
        'notes': str,
        'items': [
            {'batch_id': int, 'quantity': int, 'unit_price': Decimal, 'tax_percentage': Decimal},
            ...
        ]
    }
    """
    items_data = data.get('items', [])
    if not items_data:
        raise ValidationError("Invoice must contain at least one medicine item.")

    discount_amount = Decimal(str(data.get('discount_amount') or '0.00'))

    # Manage Customer record
    customer_name = (data.get('customer_name') or 'Customer').strip()
    customer_phone = (data.get('customer_phone') or '').strip()
    doctor_name = (data.get('doctor_name') or '').strip()

    customer = None
    if customer_phone:
        customer, _ = Customer.objects.get_or_create(
            store=store,
            phone=customer_phone,
            defaults={
                'name': customer_name,
                'doctor_name': doctor_name,
            }
        )

    invoice_number = generate_invoice_number(store)

    invoice = Invoice(
        store=store,
        invoice_number=invoice_number,
        customer=customer,
        customer_name=customer_name,
        customer_phone=customer_phone,
        doctor_name=doctor_name,
        created_by=user,
        payment_method=data.get('payment_method', Invoice.PaymentMethod.CASH),
        status=Invoice.Status.PAID,
        discount_amount=discount_amount,
        notes=data.get('notes', '')
    )
    invoice.save()

    subtotal = Decimal('0.00')
    tax_total = Decimal('0.00')

    for item in items_data:
        batch_id = item.get('batch_id')
        qty = int(item.get('quantity') or 0)
        if qty <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        if batch_id:
            # Lock batch row for concurrency safety
            batch = Batch.objects.select_for_update().get(id=batch_id, store=store)

            if batch.status != Batch.Status.ACTIVE:
                raise ValidationError(
                    f"Batch '{batch.batch_number}' for '{batch.medicine.name}' is {batch.get_status_display()} and cannot be sold."
                )
            if batch.is_expired:
                raise ValidationError(
                    f"Batch '{batch.batch_number}' for '{batch.medicine.name}' expired on {batch.expiry_date} and cannot be sold."
                )

            if batch.quantity < qty:
                raise ValidationError(
                    f"Insufficient stock for '{batch.medicine.name}' (Batch {batch.batch_number}). "
                    f"Requested: {qty}, Available: {batch.quantity}."
                )

            # Decrement stock atomically
            batch.quantity -= qty
            batch.save(update_fields=['quantity'])

            unit_price = Decimal(str(item.get('unit_price') or batch.selling_price))
            tax_pct = Decimal(str(item.get('tax_percentage') or batch.tax_percentage or '0.00'))
            med_name = batch.medicine.name
            batch_num = batch.batch_number
            exp_date = batch.expiry_date
        else:
            # Manual / Direct Entry item (not linked to inventory batch)
            batch = None
            med_name = (item.get('medicine_name') or 'Custom Item').strip()
            batch_num = (item.get('batch_number') or '').strip()
            exp_date = None
            unit_price = Decimal(str(item.get('unit_price') or '0.00'))
            tax_pct = Decimal(str(item.get('tax_percentage') or '0.00'))

        line_subtotal = unit_price * qty
        line_tax = (line_subtotal * (tax_pct / Decimal('100.00'))).quantize(Decimal('0.01'))
        line_total = line_subtotal + line_tax

        subtotal += line_subtotal
        tax_total += line_tax

        InvoiceItem.objects.create(
            store=store,
            invoice=invoice,
            batch=batch,
            medicine_name=med_name,
            batch_number=batch_num,
            expiry_date=exp_date,
            quantity=qty,
            unit_price=unit_price,
            tax_percentage=tax_pct,
            tax_amount=line_tax,
            total_price=line_total
        )

    invoice.subtotal = subtotal
    invoice.tax_amount = tax_total
    invoice.total_amount = max(Decimal('0.00'), (subtotal + tax_total - discount_amount))
    invoice.save(update_fields=['subtotal', 'tax_amount', 'total_amount'])

    return invoice


@transaction.atomic
def cancel_invoice(invoice, user):
    """
    Cancels an invoice, restores stock to corresponding batches atomically.
    """
    if invoice.status == Invoice.Status.CANCELLED:
        raise ValidationError("Invoice is already cancelled.")

    for item in invoice.items.select_related('batch'):
        if item.batch_id:
            batch = Batch.objects.select_for_update().get(id=item.batch_id)
            batch.quantity += item.quantity
            batch.save(update_fields=['quantity'])

    invoice.status = Invoice.Status.CANCELLED
    invoice.notes = (invoice.notes + f"\n[Cancelled by {user.username} on {timezone.localtime().strftime('%Y-%m-%d %I:%M %p')}]").strip()
    invoice.save(update_fields=['status', 'notes'])
    return invoice
