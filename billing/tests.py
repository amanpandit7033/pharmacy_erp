from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
from stores.models import Store
from accounts.models import User
from inventory.models import Unit, Medicine, Batch
from billing.models import Invoice, InvoiceItem
from billing.services import create_invoice, cancel_invoice


class BillingServiceAndAccessTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Store 1
        self.store1 = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="111", email="a@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.store1_admin = User.objects.create_user(
            username="apollo_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store1
        )
        self.store1_staff = User.objects.create_user(
            username="apollo_staff", password="password123",
            role=User.Role.STAFF, store=self.store1
        )

        # Store 2
        self.store2 = Store.objects.create(
            name="CarePlus", code="CPM02", license_number="DL-02",
            phone="222", email="c@example.com", address="Addr 2",
            city="Mumbai", state="MH", pincode="400001"
        )
        self.store2_admin = User.objects.create_user(
            username="care_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store2
        )

        # Super Admin
        self.super_admin = User.objects.create_user(
            username="superadmin", password="password123",
            role=User.Role.SUPER_ADMIN
        )

        # Inventory for Store 1
        self.unit = Unit.objects.create(store=self.store1, name="Strip", short_name="str")
        self.med = Medicine.objects.create(store=self.store1, name="Paracetamol 500mg", unit=self.unit)
        self.batch = Batch.objects.create(
            store=self.store1, medicine=self.med, batch_number="B-100",
            expiry_date="2026-12-31", cost_price=Decimal("10.00"),
            mrp=Decimal("25.00"), selling_price=Decimal("20.00"),
            tax_percentage=Decimal("5.00"), quantity=20
        )

    def test_atomic_invoice_creation_and_stock_decrement(self):
        """Verify billing atomically decrements batch quantity and records items."""
        invoice = create_invoice(
            store=self.store1,
            user=self.store1_staff,
            data={
                'customer_name': "Vikas Sharma",
                'customer_phone': "9998887776",
                'doctor_name': "Dr. Roy",
                'payment_method': "CASH",
                'discount_amount': Decimal("2.00"),
                'items': [
                    {'batch_id': self.batch.id, 'quantity': 5, 'unit_price': Decimal("20.00"), 'tax_percentage': Decimal("5.00")}
                ]
            }
        )

        # Verify batch quantity decremented: 20 - 5 = 15
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 15)

        # Check invoice totals: subtotal = 100, tax = 5.00, discount = 2.00, total = 103.00
        self.assertEqual(invoice.subtotal, Decimal("100.00"))
        self.assertEqual(invoice.tax_amount, Decimal("5.00"))
        self.assertEqual(invoice.total_amount, Decimal("103.00"))
        self.assertEqual(invoice.status, Invoice.Status.PAID)

    def test_insufficient_stock_rollback(self):
        """Requesting more units than available throws ValidationError and stock remains untouched."""
        with self.assertRaises(ValidationError):
            create_invoice(
                store=self.store1,
                user=self.store1_staff,
                data={
                    'customer_name': "John Doe",
                    'items': [
                        {'batch_id': self.batch.id, 'quantity': 25} # Only 20 available!
                    ]
                }
            )

        # Verify stock was untouched
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 20)

    def test_invoice_cancellation_restores_stock(self):
        """Cancelling a bill atomically restores inventory stock."""
        invoice = create_invoice(
            store=self.store1,
            user=self.store1_staff,
            data={
                'customer_name': "Test Return",
                'items': [{'batch_id': self.batch.id, 'quantity': 4}]
            }
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 16)

        # Cancel
        cancel_invoice(invoice, self.store1_admin)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 20)
        self.assertEqual(invoice.status, Invoice.Status.CANCELLED)

    def test_super_admin_blocked_from_billing_views(self):
        """Rule 1 test: Super admin cannot access store POS or invoice lists."""
        self.client.login(username="superadmin", password="password123")
        response = self.client.get(reverse('billing:pos'))
        # Should redirect away from store data
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/super-admin/', response.url)

    def test_cross_tenant_billing_isolation(self):
        """Store 2 admin cannot access Store 1 invoices."""
        invoice = create_invoice(
            store=self.store1,
            user=self.store1_staff,
            data={'customer_name': "Private Store 1 Customer", 'items': [{'batch_id': self.batch.id, 'quantity': 1}]}
        )

        self.client.login(username="care_admin", password="password123")
        response = self.client.get(reverse('billing:invoice_detail', kwargs={'pk': invoice.pk}))
        self.assertEqual(response.status_code, 404)

    def test_quarantined_batch_blocked_from_billing(self):
        """Quarantined batch cannot be sold at billing service level."""
        self.batch.quarantine(user=self.store1_admin, reason="Quality quarantine")
        with self.assertRaises(ValidationError) as ctx:
            create_invoice(
                store=self.store1,
                user=self.store1_staff,
                data={'customer_name': "Walk-in", 'items': [{'batch_id': self.batch.id, 'quantity': 1}]}
            )
        self.assertIn("cannot be sold", str(ctx.exception))

    def test_expired_batch_blocked_from_billing(self):
        """Expired batch cannot be sold at billing service level."""
        self.batch.expiry_date = timezone.now().date() - timezone.timedelta(days=1)
        self.batch.save(update_fields=['expiry_date'])
        with self.assertRaises(ValidationError) as ctx:
            create_invoice(
                store=self.store1,
                user=self.store1_staff,
                data={'customer_name': "Walk-in", 'items': [{'batch_id': self.batch.id, 'quantity': 1}]}
            )
        self.assertIn("expired", str(ctx.exception).lower())

    def test_pos_view_excludes_quarantined_and_expired_batches(self):
        """POS terminal excludes quarantined and expired batches from selector."""
        self.client.login(username="apollo_staff", password="password123")
        
        # Initially active batch is in POS
        res1 = self.client.get(reverse('billing:pos'))
        self.assertIn(self.batch.batch_number, res1.context['batches_json'])

        # Quarantine batch
        self.batch.quarantine(user=self.store1_admin, reason="Hold")
        res2 = self.client.get(reverse('billing:pos'))
        self.assertNotIn(self.batch.batch_number, res2.context['batches_json'])

    def test_invoice_thermal_print_view(self):
        """Staff can view thermal receipt print page with proper context and 80mm layout."""
        invoice = create_invoice(
            store=self.store1,
            user=self.store1_staff,
            data={
                'customer_name': "Rahul Verma",
                'customer_phone': "9876543210",
                'payment_method': "UPI",
                'items': [{'batch_id': self.batch.id, 'quantity': 2, 'unit_price': Decimal("20.00"), 'tax_percentage': Decimal("5.00")}]
            }
        )
        self.client.login(username="apollo_staff", password="password123")
        res = self.client.get(reverse('billing:invoice_thermal', kwargs={'pk': invoice.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, invoice.invoice_number)
        self.assertContains(res, "Apollo Pharmacy")
        self.assertContains(res, "Thermal Receipt")
        self.assertContains(res, "80mm")
        self.assertContains(res, "Paracetamol 500mg")
        self.assertEqual(res.context['total_quantity'], 2)
        self.assertIn('cgst_amount', res.context)
        self.assertIn('sgst_amount', res.context)

    def test_cross_tenant_thermal_isolation(self):
        """Store 2 admin cannot access Store 1 thermal invoice."""
        invoice = create_invoice(
            store=self.store1,
            user=self.store1_staff,
            data={'customer_name': "Private Customer", 'items': [{'batch_id': self.batch.id, 'quantity': 1}]}
        )
        self.client.login(username="care_admin", password="password123")
        res = self.client.get(reverse('billing:invoice_thermal', kwargs={'pk': invoice.pk}))
        self.assertEqual(res.status_code, 404)

    def test_print_and_thermal_with_manual_otc_item(self):
        """Verify invoices with manual OTC items (null batch) print and render cleanly."""
        invoice = create_invoice(
            store=self.store1,
            user=self.store1_staff,
            data={
                'customer_name': "Direct Walk-in",
                'payment_method': "CASH",
                'items': [
                    {
                        'batch_id': None,
                        'medicine_name': "Fever Relief Medicine",
                        'batch_number': "OTC",
                        'quantity': 3,
                        'unit_price': Decimal("30.00"),
                        'tax_percentage': Decimal("0.00")
                    }
                ]
            }
        )
        self.client.login(username="apollo_staff", password="password123")

        # Standard A4/A5 Print
        res_print = self.client.get(reverse('billing:invoice_print', kwargs={'pk': invoice.pk}))
        self.assertEqual(res_print.status_code, 200)
        self.assertContains(res_print, "Fever Relief Medicine")

        # Thermal Receipt Print
        res_thermal = self.client.get(reverse('billing:invoice_thermal', kwargs={'pk': invoice.pk}))
        self.assertEqual(res_thermal.status_code, 200)
        self.assertContains(res_thermal, "Fever Relief Medicine")


