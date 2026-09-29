from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from stores.models import Store


class StoreListViewFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.superadmin = User.objects.create_superuser(
            username="superadmin", email="super@example.com", password="password123",
            role=User.Role.SUPER_ADMIN
        )

        self.store1 = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-1111",
            phone="9876543210", email="apollo@example.com", address="Connaught Place",
            city="New Delhi", state="Delhi", pincode="110001", is_active=True
        )
        self.store2 = Store.objects.create(
            name="MedPlus Pharmacy", code="MED02", license_number="DL-2222",
            phone="9123456789", email="medplus@example.com", address="Bandra West",
            city="Mumbai", state="Maharashtra", pincode="400050", is_active=False
        )

    def test_store_list_search_query(self):
        self.client.login(username="superadmin", password="password123")
        # Search by city
        res = self.client.get(reverse('stores:store_list') + '?q=Mumbai')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['stores']), 1)
        self.assertEqual(res.context['stores'][0].pk, self.store2.pk)

        # Search by code
        res2 = self.client.get(reverse('stores:store_list') + '?q=APL01')
        self.assertEqual(len(res2.context['stores']), 1)
        self.assertEqual(res2.context['stores'][0].pk, self.store1.pk)

    def test_store_list_status_filter(self):
        self.client.login(username="superadmin", password="password123")
        # Active only
        res_active = self.client.get(reverse('stores:store_list') + '?status=active')
        self.assertEqual(len(res_active.context['stores']), 1)
        self.assertEqual(res_active.context['stores'][0].pk, self.store1.pk)

        # Inactive only
        res_inactive = self.client.get(reverse('stores:store_list') + '?status=inactive')
        self.assertEqual(len(res_inactive.context['stores']), 1)
        self.assertEqual(res_inactive.context['stores'][0].pk, self.store2.pk)

    def test_store_list_state_filter(self):
        self.client.login(username="superadmin", password="password123")
        res = self.client.get(reverse('stores:store_list') + '?state=Delhi')
        self.assertEqual(len(res.context['stores']), 1)
        self.assertEqual(res.context['stores'][0].pk, self.store1.pk)

    def test_store_list_sorting(self):
        self.client.login(username="superadmin", password="password123")
        # Name A-Z: Apollo first
        res_asc = self.client.get(reverse('stores:store_list') + '?sort=name_asc')
        self.assertEqual(res_asc.context['stores'][0].pk, self.store1.pk)

        # Name Z-A: MedPlus first
        res_desc = self.client.get(reverse('stores:store_list') + '?sort=name_desc')
        self.assertEqual(res_desc.context['stores'][0].pk, self.store2.pk)


class StoreLogoAndSettingsTests(TestCase):
    def setUp(self):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from billing.services import create_invoice
        from inventory.models import Unit, Medicine, Batch

        self.client = Client()
        self.store = Store.objects.create(
            name="Apex Pharmacy", code="APX01", license_number="DL-APX-99",
            phone="9876543210", email="apex@example.com", address="Main Bazaar",
            city="Jaipur", state="Rajasthan", pincode="302001", is_active=True
        )
        self.store_admin = User.objects.create_user(
            username="apex_admin", email="admin@apex.com", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store
        )

        unit = Unit.objects.create(store=self.store, name="Strip", short_name="str")
        med = Medicine.objects.create(store=self.store, name="Paracetamol", unit=unit)
        batch = Batch.objects.create(
            store=self.store, medicine=med, batch_number="B-1", expiry_date="2027-01-01",
            cost_price=10, mrp=20, selling_price=15, tax_percentage=5, quantity=50
        )
        self.invoice = create_invoice(
            store=self.store, user=self.store_admin,
            data={'customer_name': "Rahul Verma", 'items': [{'batch_id': batch.id, 'quantity': 1}]}
        )

    def _get_test_image(self):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        file = BytesIO()
        image = Image.new('RGB', (100, 100), color=(45, 104, 240))
        image.save(file, 'jpeg')
        file.seek(0)
        return SimpleUploadedFile('test_logo.jpg', file.getvalue(), content_type='image/jpeg')

    def test_store_settings_page_accessible(self):
        self.client.login(username="apex_admin", password="password123")
        res = self.client.get(reverse('stores:settings'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Pharmacy Store Logo')
        self.assertContains(res, 'enctype="multipart/form-data"')

    def test_upload_and_remove_store_logo(self):
        self.client.login(username="apex_admin", password="password123")
        test_img = self._get_test_image()

        # Upload logo
        res = self.client.post(reverse('stores:settings'), {
            'name': 'Apex Pharmacy Updated',
            'phone': '9876543210',
            'email': 'apex@example.com',
            'license_number': 'DL-APX-99',
            'address': 'Main Bazaar',
            'city': 'Jaipur',
            'state': 'Rajasthan',
            'pincode': '302001',
            'currency': '₹',
            'tax_label': 'GST',
            'logo': test_img
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        self.store.refresh_from_db()
        self.assertTrue(bool(self.store.logo))
        self.assertIn('store_logos/test_logo', self.store.logo.name)

        # Verify logo appears in Invoice Detail and Invoice Print
        detail_res = self.client.get(reverse('billing:invoice_detail', kwargs={'pk': self.invoice.pk}))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, self.store.logo.url)

        print_res = self.client.get(reverse('billing:invoice_print', kwargs={'pk': self.invoice.pk}))
        self.assertEqual(print_res.status_code, 200)
        self.assertContains(print_res, self.store.logo.url)

        # Now remove the logo
        res_remove = self.client.post(reverse('stores:settings'), {
            'name': 'Apex Pharmacy Updated',
            'phone': '9876543210',
            'email': 'apex@example.com',
            'license_number': 'DL-APX-99',
            'address': 'Main Bazaar',
            'city': 'Jaipur',
            'state': 'Rajasthan',
            'pincode': '302001',
            'currency': '₹',
            'tax_label': 'GST',
            'remove_logo': '1'
        }, follow=True)
        self.assertEqual(res_remove.status_code, 200)

        self.store.refresh_from_db()
        self.assertFalse(bool(self.store.logo))

