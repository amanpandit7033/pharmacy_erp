from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from stores.models import Store
from accounts.models import User
from inventory.models import Unit, Medicine, Batch
from billing.models import Invoice, InvoiceItem


class StoreStaffAndAnalyticsTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Store 1
        self.store1 = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="111", email="apollo@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.store1_admin = User.objects.create_user(
            username="apollo_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store1
        )
        self.store1_staff1 = User.objects.create_user(
            username="apollo_staff1", password="password123",
            first_name="Ramesh", last_name="Kumar",
            role=User.Role.STAFF, store=self.store1
        )
        self.store1_staff2 = User.objects.create_user(
            username="apollo_staff2", password="password123",
            first_name="Sita", last_name="Sharma",
            role=User.Role.STAFF, store=self.store1
        )

        # Store 2
        self.store2 = Store.objects.create(
            name="CarePlus Pharmacy", code="CPM02", license_number="DL-02",
            phone="222", email="care@example.com", address="Addr 2",
            city="Mumbai", state="Maharashtra", pincode="400001"
        )
        self.store2_admin = User.objects.create_user(
            username="care_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store2
        )
        self.store2_staff1 = User.objects.create_user(
            username="care_staff1", password="password123",
            first_name="Amit", last_name="Patel",
            role=User.Role.STAFF, store=self.store2
        )

        # Super Admin
        self.super_admin = User.objects.create_user(
            username="superadmin", password="password123",
            role=User.Role.SUPER_ADMIN, is_superuser=True
        )

        # Inventory setup for Store 1
        self.unit = Unit.objects.create(store=self.store1, name="Strip", short_name="str")
        self.med1 = Medicine.objects.create(
            store=self.store1, name="Paracetamol 650", unit=self.unit
        )
        self.batch1 = Batch.objects.create(
            store=self.store1, medicine=self.med1, batch_number="B001",
            expiry_date=timezone.now().date() + timedelta(days=180),
            cost_price=Decimal("15.00"), mrp=Decimal("30.00"),
            selling_price=Decimal("25.00"), quantity=100
        )

        # Invoices for Store 1 (Today & Yesterday)
        self.inv1 = Invoice.objects.create(
            store=self.store1, invoice_number="INV-001", customer_name="John Doe",
            created_by=self.store1_staff1, status=Invoice.Status.PAID,
            subtotal=Decimal("50.00"), tax_amount=Decimal("0.00"),
            discount_amount=Decimal("0.00"), total_amount=Decimal("50.00")
        )
        self.inv_item1 = InvoiceItem.objects.create(
            store=self.store1, invoice=self.inv1, batch=self.batch1,
            medicine_name="Paracetamol 650", batch_number="B001",
            expiry_date=self.batch1.expiry_date, quantity=2,
            unit_price=Decimal("25.00"), total_price=Decimal("50.00")
        )

    # =========================================================================
    # FEATURE 1: STORE STAFF DIRECTORY FOR SUPER ADMIN
    # =========================================================================

    def test_super_admin_can_access_all_staff_list(self):
        """Super Admin can access the cross-store staff directory."""
        self.client.login(username="superadmin", password="password123")
        url = reverse('accounts:all_staff_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/all_staff_list.html')
        # All 3 staff members should be in the list
        staff_usernames = [s.username for s in response.context['staff_members']]
        self.assertIn("apollo_staff1", staff_usernames)
        self.assertIn("apollo_staff2", staff_usernames)
        self.assertIn("care_staff1", staff_usernames)
        self.assertEqual(response.context['total_staff_count'], 3)
        self.assertEqual(response.context['stores_represented_count'], 2)

    def test_store_admin_and_staff_cannot_access_all_staff_list(self):
        """Store Admin and Staff cannot access the platform-wide staff directory."""
        # Store Admin blocked
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get(reverse('accounts:all_staff_list'))
        self.assertIn(res.status_code, [302, 403])

        # Staff blocked
        self.client.login(username="apollo_staff1", password="password123")
        res2 = self.client.get(reverse('accounts:all_staff_list'))
        self.assertIn(res2.status_code, [302, 403])

    def test_super_admin_filter_staff_by_store(self):
        """Super Admin can filter staff members by specific store."""
        self.client.login(username="superadmin", password="password123")
        url = reverse('accounts:all_staff_list') + f"?store={self.store1.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        staff_usernames = [s.username for s in response.context['staff_members']]
        self.assertIn("apollo_staff1", staff_usernames)
        self.assertIn("apollo_staff2", staff_usernames)
        self.assertNotIn("care_staff1", staff_usernames)

    def test_super_admin_search_staff(self):
        """Super Admin can search staff by name or username."""
        self.client.login(username="superadmin", password="password123")
        url = reverse('accounts:all_staff_list') + "?q=Ramesh"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        staff_usernames = [s.username for s in response.context['staff_members']]
        self.assertIn("apollo_staff1", staff_usernames)
        self.assertNotIn("apollo_staff2", staff_usernames)

    def test_super_admin_can_toggle_staff_status(self):
        """Super Admin can activate or deactivate staff and gets redirected back."""
        self.client.login(username="superadmin", password="password123")
        url = reverse('accounts:staff_toggle', kwargs={'pk': self.store2_staff1.pk})
        response = self.client.post(url)
        self.assertRedirects(response, reverse('accounts:all_staff_list'))
        self.store2_staff1.refresh_from_db()
        self.assertFalse(self.store2_staff1.is_active)

    # =========================================================================
    # FEATURE 2: ANALYTICS REPORT (PROFIT & LOSS, GROWTH & DOWN TRACKING)
    # =========================================================================

    def test_super_admin_analytics_report_view(self):
        """Super Admin sees platform financial overview and store rankings."""
        self.client.login(username="superadmin", password="password123")
        url = reverse('dashboard:analytics_report')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/analytics_super_admin.html')
        self.assertIn('curr_fin', response.context)
        self.assertIn('stores_analytics', response.context)
        self.assertIn('growing_count', response.context)
        self.assertIn('down_count', response.context)

        # Revenue should reflect the invoice of 50.00
        curr_fin = response.context['curr_fin']
        self.assertEqual(curr_fin['revenue'], Decimal('50.00'))
        # COGS = 2 units * 15.00 cost price = 30.00
        self.assertEqual(curr_fin['cogs'], Decimal('30.00'))
        # Gross profit = 50.00 - 30.00 = 20.00
        self.assertEqual(curr_fin['gross_profit'], Decimal('20.00'))
        self.assertEqual(curr_fin['gross_margin_pct'], 40.0)

    def test_super_admin_analytics_filter_by_store(self):
        """Super Admin can filter analytics down to a single store."""
        self.client.login(username="superadmin", password="password123")
        url = reverse('dashboard:analytics_report') + f"?store={self.store1.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_store'], self.store1)
        self.assertEqual(response.context['curr_fin']['revenue'], Decimal('50.00'))

    def test_store_admin_analytics_report_view(self):
        """Store Admin sees their store's P&L and top profitable medicines."""
        self.client.login(username="apollo_admin", password="password123")
        url = reverse('dashboard:analytics_report')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/analytics_store_admin.html')

        curr_fin = response.context['curr_fin']
        self.assertEqual(curr_fin['revenue'], Decimal('50.00'))
        self.assertEqual(curr_fin['cogs'], Decimal('30.00'))
        self.assertEqual(curr_fin['gross_profit'], Decimal('20.00'))
        self.assertIn('profitable_medicines', response.context)
        self.assertEqual(len(response.context['profitable_medicines']), 1)
        self.assertEqual(response.context['profitable_medicines'][0]['medicine_name'], "Paracetamol 650")
        self.assertEqual(response.context['profitable_medicines'][0]['profit'], Decimal('20.00'))

    def test_staff_analytics_report_view_protects_cost_price(self):
        """Staff members see their sales performance but cost prices and margins are hidden."""
        self.client.login(username="apollo_staff1", password="password123")
        url = reverse('dashboard:analytics_report')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/analytics_staff.html')
        self.assertEqual(response.context['my_sales'], Decimal('50.00'))
        self.assertEqual(response.context['my_count'], 1)
        # Verify wholesale cost price and margins are not in staff context
        self.assertNotIn('cogs', response.context)
        self.assertNotIn('curr_fin', response.context)
        self.assertNotIn('gross_profit', response.context)

    def test_unauthenticated_user_redirected_to_login(self):
        """Anonymous user trying to access analytics is redirected to login."""
        url = reverse('dashboard:analytics_report')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
