from decimal import Decimal
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from billing.models import Invoice, InvoiceItem, Customer, InvoicePayment
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
    Supports:
      1. Loose sales (e.g. 2 tablets out of 10-tablet strip with fractional stock deduction)
      2. Product-wise flat & percentage discounts
      3. Partial payment and due balance recording
    """
    items_data = data.get('items', [])
    if not items_data:
        raise ValidationError("Invoice must contain at least one medicine item.")

    overall_bill_discount = Decimal(str(data.get('discount_amount') or '0.00'))

    # Manage Customer record
    customer_name = (data.get('customer_name') or 'Customer').strip()
    customer_phone = (data.get('customer_phone') or '').strip()
    customer_address = (data.get('customer_address') or '').strip()
    doctor_name = (data.get('doctor_name') or '').strip()

    customer = None
    if customer_phone:
        customer, created = Customer.objects.get_or_create(
            store=store,
            phone=customer_phone,
            defaults={
                'name': customer_name,
                'address': customer_address,
                'doctor_name': doctor_name,
            }
        )
        if not created and customer_address and not customer.address:
            customer.address = customer_address
            customer.save(update_fields=['address'])

    invoice_number = generate_invoice_number(store)

    invoice = Invoice(
        store=store,
        invoice_number=invoice_number,
        customer=customer,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_address=customer_address,
        doctor_name=doctor_name,
        created_by=user,
        payment_method=data.get('payment_method', Invoice.PaymentMethod.CASH),
        status=Invoice.Status.PAID,
        discount_amount=Decimal('0.00'),
        notes=data.get('notes', '')
    )
    invoice.save()

    subtotal = Decimal('0.00')
    tax_total = Decimal('0.00')
    total_item_discounts = Decimal('0.00')

    for item in items_data:
        batch_id = item.get('batch_id')
        is_loose = bool(item.get('is_loose', False))
        unit_mode = str(item.get('unit_mode') or ('LOOSE' if is_loose else 'STRIP')).upper()
        strips_per_box = int(item.get('strips_per_box') or 1)
        if strips_per_box <= 0:
            strips_per_box = 1
        pack_size = int(item.get('pack_size') or 1)
        if pack_size <= 0:
            pack_size = 1

        if unit_mode == 'BOX':
            is_loose = False
            loose_qty = 0
            box_qty = Decimal(str(item.get('quantity') or 0))
            if box_qty <= Decimal('0.00'):
                raise ValidationError("Box quantity must be greater than zero.")
            item_qty = box_qty
            qty_deduct = box_qty * Decimal(str(strips_per_box))
            line_gross_units = box_qty
        elif unit_mode == 'LOOSE' or is_loose:
            unit_mode = 'LOOSE'
            is_loose = True
            loose_qty = int(item.get('loose_quantity') or item.get('loose_qty') or item.get('quantity') or 0)
            if loose_qty <= 0:
                raise ValidationError("Loose quantity must be greater than zero.")
            pack_fraction = (Decimal(str(loose_qty)) / Decimal(str(pack_size))).quantize(Decimal('0.01'))
            if pack_fraction == Decimal('0.00'):
                pack_fraction = Decimal('0.01')
            item_qty = pack_fraction
            qty_deduct = pack_fraction
            line_gross_units = Decimal(str(loose_qty))
        else:
            unit_mode = 'STRIP'
            is_loose = False
            loose_qty = 0
            qty = Decimal(str(item.get('quantity') or 0))
            if qty <= Decimal('0.00'):
                raise ValidationError("Quantity must be greater than zero.")
            item_qty = qty
            qty_deduct = qty
            line_gross_units = qty

        if batch_id:
            batch = Batch.objects.select_for_update().get(id=batch_id, store=store)

            if batch.status != Batch.Status.ACTIVE:
                raise ValidationError(
                    f"Batch '{batch.batch_number}' for '{batch.medicine.name}' is {batch.get_status_display()} and cannot be sold."
                )
            if batch.is_expired:
                raise ValidationError(
                    f"Batch '{batch.batch_number}' for '{batch.medicine.name}' expired on {batch.expiry_date} and cannot be sold."
                )

            if batch.quantity < qty_deduct:
                raise ValidationError(
                    f"Insufficient stock for '{batch.medicine.name}' (Batch {batch.batch_number}). "
                    f"Requested: {qty_deduct}, Available: {batch.quantity}."
                )

            batch.quantity -= qty_deduct
            batch.save(update_fields=['quantity'])

            if unit_mode == 'BOX':
                if item.get('unit_price'):
                    unit_price = Decimal(str(item.get('unit_price')))
                else:
                    unit_price = (Decimal(str(batch.selling_price)) * Decimal(str(strips_per_box))).quantize(Decimal('0.01'))
            elif unit_mode == 'LOOSE':
                if item.get('unit_price'):
                    unit_price = Decimal(str(item.get('unit_price')))
                else:
                    unit_price = (Decimal(str(batch.selling_price)) / Decimal(str(pack_size))).quantize(Decimal('0.01'))
            else:
                unit_price = Decimal(str(item.get('unit_price') or batch.selling_price))

            tax_pct = Decimal(str(item.get('tax_percentage') or batch.tax_percentage or '0.00'))
            med_name = batch.medicine.name
            batch_num = batch.batch_number
            exp_date = batch.expiry_date
        else:
            batch = None
            med_name = (item.get('medicine_name') or 'Custom Item').strip()
            batch_num = (item.get('batch_number') or '').strip()
            exp_date = None
            unit_price = Decimal(str(item.get('unit_price') or '0.00'))
            tax_pct = Decimal(str(item.get('tax_percentage') or '0.00'))

        # Line Gross Calculation
        line_gross = (line_gross_units * unit_price).quantize(Decimal('0.01'))

        # Product-wise Discount Calculation
        disc_type = item.get('discount_type', 'FLAT')
        raw_disc_val = str(item.get('discount_value') or item.get('discount_val') or '0.00').strip()
        if raw_disc_val.endswith('%'):
            disc_type = 'PERCENT'
            raw_disc_val = raw_disc_val.rstrip('%').strip()
        try:
            disc_val = Decimal(raw_disc_val or '0.00')
        except Exception:
            disc_val = Decimal('0.00')

        if disc_type == 'PERCENT':
            line_disc = (line_gross * (disc_val / Decimal('100.00'))).quantize(Decimal('0.01'))
        else:
            line_disc = min(line_gross, disc_val.quantize(Decimal('0.01')))
        line_disc = max(Decimal('0.00'), line_disc)

        line_taxable = line_gross - line_disc
        line_tax = (line_taxable * (tax_pct / Decimal('100.00'))).quantize(Decimal('0.01'))
        line_total = line_taxable + line_tax

        subtotal += line_gross
        total_item_discounts += line_disc
        tax_total += line_tax

        InvoiceItem.objects.create(
            store=store,
            invoice=invoice,
            batch=batch,
            medicine_name=med_name,
            batch_number=batch_num,
            expiry_date=exp_date,
            quantity=item_qty,
            unit_mode=unit_mode,
            strips_per_box=strips_per_box,
            is_loose=is_loose,
            pack_size=pack_size,
            loose_quantity=loose_qty,
            discount_type=disc_type,
            discount_value=disc_val,
            discount_amount=line_disc,
            unit_price=unit_price,
            tax_percentage=tax_pct,
            tax_amount=line_tax,
            total_price=line_total
        )

    total_discount = total_item_discounts + overall_bill_discount
    grand_total = max(Decimal('0.00'), (subtotal - total_item_discounts + tax_total - overall_bill_discount)).quantize(Decimal('0.01'))

    # Partial / Due Amount Logic
    paid_input = data.get('paid_amount')
    if paid_input is not None and str(paid_input).strip() != '':
        try:
            paid = Decimal(str(paid_input)).quantize(Decimal('0.01'))
        except Exception:
            paid = grand_total
    else:
        paid = grand_total

    if paid >= grand_total:
        paid = grand_total
        due = Decimal('0.00')
        status = Invoice.Status.PAID
    elif paid > Decimal('0.00'):
        due = grand_total - paid
        status = Invoice.Status.PARTIAL
    else:
        paid = Decimal('0.00')
        due = grand_total
        status = Invoice.Status.DUE

    invoice.subtotal = subtotal
    invoice.tax_amount = tax_total
    invoice.discount_amount = total_discount
    invoice.total_amount = grand_total
    invoice.paid_amount = paid
    invoice.due_amount = due
    invoice.status = status
    invoice.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total_amount', 'paid_amount', 'due_amount', 'status'])

    # Record initial payment if customer paid any amount
    if paid > Decimal('0.00'):
        InvoicePayment.objects.create(
            store=store,
            invoice=invoice,
            amount=paid,
            payment_method=invoice.payment_method,
            notes="Initial billing checkout payment",
            created_by=user
        )

    return invoice


@transaction.atomic
def cancel_invoice(invoice, user, reason=''):
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
    timestamp_str = timezone.localtime().strftime('%Y-%m-%d %I:%M %p')
    reason_suffix = f" - Reason: {reason}" if reason else ""
    invoice.notes = (invoice.notes + f"\n[Cancelled by {user.username} on {timestamp_str}{reason_suffix}]").strip()
    invoice.save(update_fields=['status', 'notes'])
    return invoice


@transaction.atomic
def update_invoice(invoice, user, data):
    """
    Edits an existing invoice. Atomically restores previous batch stock,
    validates new items, deducts updated batch stock, replaces line items,
    and updates customer, discounts, paid/due amounts and invoice totals.
    """
    if invoice.status == Invoice.Status.CANCELLED:
        raise ValidationError("Cancelled invoices cannot be edited.")

    items_data = data.get('items', [])
    if not items_data:
        raise ValidationError("Invoice must contain at least one medicine item.")

    overall_bill_discount = Decimal(str(data.get('discount_amount') or '0.00'))
    store = invoice.store

    # 1. Atomically restore previously deducted batch stock
    for old_item in invoice.items.select_related('batch'):
        if old_item.batch_id:
            old_batch = Batch.objects.select_for_update().get(id=old_item.batch_id, store=store)
            old_batch.quantity += old_item.quantity
            old_batch.save(update_fields=['quantity'])

    # 2. Clear old invoice items
    invoice.items.all().delete()

    # 3. Process new items and deduct stock
    subtotal = Decimal('0.00')
    tax_total = Decimal('0.00')
    total_item_discounts = Decimal('0.00')

    for item in items_data:
        batch_id = item.get('batch_id')
        is_loose = bool(item.get('is_loose', False))
        unit_mode = str(item.get('unit_mode') or ('LOOSE' if is_loose else 'STRIP')).upper()
        strips_per_box = int(item.get('strips_per_box') or 1)
        if strips_per_box <= 0:
            strips_per_box = 1
        pack_size = int(item.get('pack_size') or 1)
        if pack_size <= 0:
            pack_size = 1

        if unit_mode == 'BOX':
            is_loose = False
            loose_qty = 0
            box_qty = Decimal(str(item.get('quantity') or 0))
            if box_qty <= Decimal('0.00'):
                raise ValidationError("Box quantity must be greater than zero.")
            item_qty = box_qty
            qty_deduct = box_qty * Decimal(str(strips_per_box))
            line_gross_units = box_qty
        elif unit_mode == 'LOOSE' or is_loose:
            unit_mode = 'LOOSE'
            is_loose = True
            loose_qty = int(item.get('loose_quantity') or item.get('loose_qty') or item.get('quantity') or 0)
            if loose_qty <= 0:
                raise ValidationError("Loose quantity must be greater than zero.")
            pack_fraction = (Decimal(str(loose_qty)) / Decimal(str(pack_size))).quantize(Decimal('0.01'))
            if pack_fraction == Decimal('0.00'):
                pack_fraction = Decimal('0.01')
            item_qty = pack_fraction
            qty_deduct = pack_fraction
            line_gross_units = Decimal(str(loose_qty))
        else:
            unit_mode = 'STRIP'
            is_loose = False
            loose_qty = 0
            qty = Decimal(str(item.get('quantity') or 0))
            if qty <= Decimal('0.00'):
                raise ValidationError("Quantity must be greater than zero.")
            item_qty = qty
            qty_deduct = qty
            line_gross_units = qty

        if batch_id:
            batch = Batch.objects.select_for_update().get(id=batch_id, store=store)

            if batch.status != Batch.Status.ACTIVE:
                raise ValidationError(
                    f"Batch '{batch.batch_number}' for '{batch.medicine.name}' is {batch.get_status_display()} and cannot be sold."
                )
            if batch.is_expired:
                raise ValidationError(
                    f"Batch '{batch.batch_number}' for '{batch.medicine.name}' expired on {batch.expiry_date} and cannot be sold."
                )

            if batch.quantity < qty_deduct:
                raise ValidationError(
                    f"Insufficient stock for '{batch.medicine.name}' (Batch {batch.batch_number}). "
                    f"Requested: {qty_deduct}, Available: {batch.quantity}."
                )

            batch.quantity -= qty_deduct
            batch.save(update_fields=['quantity'])

            if unit_mode == 'BOX':
                if item.get('unit_price'):
                    unit_price = Decimal(str(item.get('unit_price')))
                else:
                    unit_price = (Decimal(str(batch.selling_price)) * Decimal(str(strips_per_box))).quantize(Decimal('0.01'))
            elif unit_mode == 'LOOSE':
                if item.get('unit_price'):
                    unit_price = Decimal(str(item.get('unit_price')))
                else:
                    unit_price = (Decimal(str(batch.selling_price)) / Decimal(str(pack_size))).quantize(Decimal('0.01'))
            else:
                unit_price = Decimal(str(item.get('unit_price') or batch.selling_price))

            tax_pct = Decimal(str(item.get('tax_percentage') or batch.tax_percentage or '0.00'))
            med_name = batch.medicine.name
            batch_num = batch.batch_number
            exp_date = batch.expiry_date
        else:
            batch = None
            med_name = (item.get('medicine_name') or 'Custom Item').strip()
            batch_num = (item.get('batch_number') or '').strip()
            exp_date = None
            unit_price = Decimal(str(item.get('unit_price') or '0.00'))
            tax_pct = Decimal(str(item.get('tax_percentage') or '0.00'))

        line_gross = (line_gross_units * unit_price).quantize(Decimal('0.01'))

        # Product-wise Discount Calculation
        disc_type = item.get('discount_type', 'FLAT')
        raw_disc_val = str(item.get('discount_value') or item.get('discount_val') or '0.00').strip()
        if raw_disc_val.endswith('%'):
            disc_type = 'PERCENT'
            raw_disc_val = raw_disc_val.rstrip('%').strip()
        try:
            disc_val = Decimal(raw_disc_val or '0.00')
        except Exception:
            disc_val = Decimal('0.00')

        if disc_type == 'PERCENT':
            line_disc = (line_gross * (disc_val / Decimal('100.00'))).quantize(Decimal('0.01'))
        else:
            line_disc = min(line_gross, disc_val.quantize(Decimal('0.01')))
        line_disc = max(Decimal('0.00'), line_disc)

        line_taxable = line_gross - line_disc
        line_tax = (line_taxable * (tax_pct / Decimal('100.00'))).quantize(Decimal('0.01'))
        line_total = line_taxable + line_tax

        subtotal += line_gross
        total_item_discounts += line_disc
        tax_total += line_tax

        InvoiceItem.objects.create(
            store=store,
            invoice=invoice,
            batch=batch,
            medicine_name=med_name,
            batch_number=batch_num,
            expiry_date=exp_date,
            quantity=item_qty,
            unit_mode=unit_mode,
            strips_per_box=strips_per_box,
            is_loose=is_loose,
            pack_size=pack_size,
            loose_quantity=loose_qty,
            discount_type=disc_type,
            discount_value=disc_val,
            discount_amount=line_disc,
            unit_price=unit_price,
            tax_percentage=tax_pct,
            tax_amount=line_tax,
            total_price=line_total
        )

    # 4. Manage Customer record
    customer_name = (data.get('customer_name') or invoice.customer_name or 'Customer').strip()
    customer_phone = (data.get('customer_phone') or '').strip()
    customer_address = (data.get('customer_address') or '').strip()
    doctor_name = (data.get('doctor_name') or '').strip()

    customer = None
    if customer_phone:
        customer, created = Customer.objects.get_or_create(
            store=store,
            phone=customer_phone,
            defaults={
                'name': customer_name,
                'address': customer_address,
                'doctor_name': doctor_name,
            }
        )
        if not created:
            update_fields = []
            if customer_name and customer.name != customer_name:
                customer.name = customer_name
                update_fields.append('name')
            if customer_address and customer.address != customer_address:
                customer.address = customer_address
                update_fields.append('address')
            if doctor_name and customer.doctor_name != doctor_name:
                customer.doctor_name = doctor_name
                update_fields.append('doctor_name')
            if update_fields:
                customer.save(update_fields=update_fields)

    # 5. Update Invoice fields
    invoice.customer = customer
    invoice.customer_name = customer_name
    invoice.customer_phone = customer_phone
    invoice.customer_address = customer_address
    invoice.doctor_name = doctor_name
    if 'payment_method' in data and data['payment_method']:
        invoice.payment_method = data['payment_method']

    total_discount = total_item_discounts + overall_bill_discount
    grand_total = max(Decimal('0.00'), (subtotal - total_item_discounts + tax_total - overall_bill_discount)).quantize(Decimal('0.01'))

    # Update paid & due
    paid_input = data.get('paid_amount')
    if paid_input is not None and str(paid_input).strip() != '':
        try:
            paid = Decimal(str(paid_input)).quantize(Decimal('0.01'))
        except Exception:
            paid = invoice.paid_amount
    else:
        paid = invoice.paid_amount

    if paid >= grand_total:
        paid = grand_total
        due = Decimal('0.00')
        status = Invoice.Status.PAID
    elif paid > Decimal('0.00'):
        due = grand_total - paid
        status = Invoice.Status.PARTIAL
    else:
        paid = Decimal('0.00')
        due = grand_total
        status = Invoice.Status.DUE

    invoice.discount_amount = total_discount
    invoice.subtotal = subtotal
    invoice.tax_amount = tax_total
    invoice.total_amount = grand_total
    invoice.paid_amount = paid
    invoice.due_amount = due
    invoice.status = status

    if 'notes' in data and data['notes']:
        invoice.notes = data['notes']

    audit_note = f"\n[Edited by {user.username} on {timezone.localtime().strftime('%Y-%m-%d %I:%M %p')}]"
    if audit_note not in invoice.notes:
        invoice.notes = (invoice.notes + audit_note).strip()

    invoice.save()
    return invoice


@transaction.atomic
def collect_invoice_due(invoice, amount, payment_method, user, notes=''):
    """
    Collects a due payment for an invoice with DUE or PARTIAL status.
    Atomically updates invoice.paid_amount, invoice.due_amount, invoice.status,
    and creates an InvoicePayment record.
    """
    if invoice.status not in [Invoice.Status.PARTIAL, Invoice.Status.DUE]:
        raise ValidationError(f"Invoice #{invoice.invoice_number} has status '{invoice.get_status_display()}' and cannot accept due payments.")

    amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    if amount <= Decimal('0.00'):
        raise ValidationError("Payment amount must be greater than zero.")

    if amount > invoice.due_amount:
        raise ValidationError(
            f"Payment amount ({invoice.store.currency}{amount}) cannot exceed current due balance ({invoice.store.currency}{invoice.due_amount})."
        )

    payment = InvoicePayment.objects.create(
        store=invoice.store,
        invoice=invoice,
        amount=amount,
        payment_method=payment_method,
        notes=notes or f"Due balance collected by {user.username}",
        created_by=user
    )

    invoice.paid_amount += amount
    invoice.due_amount -= amount
    if invoice.due_amount <= Decimal('0.00'):
        invoice.due_amount = Decimal('0.00')
        invoice.status = Invoice.Status.PAID
    else:
        invoice.status = Invoice.Status.PARTIAL

    audit_note = f"\n[Due payment of {invoice.store.currency}{amount} collected via {payment_method} by {user.username} on {timezone.localtime().strftime('%Y-%m-%d %I:%M %p')}]"
    invoice.notes = (invoice.notes + audit_note).strip()
    invoice.save(update_fields=['paid_amount', 'due_amount', 'status', 'notes'])

    return payment
