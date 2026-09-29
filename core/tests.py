from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.core.exceptions import PermissionDenied
from django.views.generic import ListView
from stores.models import Store
from accounts.models import User
from inventory.models import Category, Unit, Medicine, Batch
from core.mixins import RoleRequiredMixin, TenantAccessMixin


class DummyStoreView(TenantAccessMixin, RoleRequiredMixin, ListView):
    model = Medicine
    allowed_roles = ['store_admin', 'staff']


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # Store 1
        self.store1 = Store.objects.create(
            name="Care Pharmacy", code="CARE01", license_number="DL-01",
            phone="1111111111", email="care@example.com",
            address="Street 1", city="Delhi", state="Delhi", pincode="110001"
        )
        self.store1_admin = User.objects.create_user(
            username="care_admin", password="password",
            role=User.Role.STORE_ADMIN, store=self.store1
        )
        
        # Store 2
        self.store2 = Store.objects.create(
            name="Heal Pharmacy", code="HEAL02", license_number="DL-02",
            phone="2222222222", email="heal@example.com",
            address="Street 2", city="Mumbai", state="Maharashtra", pincode="400001"
        )
        self.store2_admin = User.objects.create_user(
            username="heal_admin", password="password",
            role=User.Role.STORE_ADMIN, store=self.store2
        )
        
        # Super Admin
        self.super_admin = User.objects.create_user(
            username="boss", password="password",
            role=User.Role.SUPER_ADMIN
        )

        # Inventory fixtures
        self.unit1 = Unit.objects.create(name="Strip", short_name="str", store=self.store1)
        self.unit2 = Unit.objects.create(name="Strip", short_name="str", store=self.store2)

        self.med1 = Medicine.objects.create(
            store=self.store1, name="Paracetamol Care", unit=self.unit1
        )
        self.med2 = Medicine.objects.create(
            store=self.store2, name="Ibuprofen Heal", unit=self.unit2
        )

    def test_tenant_manager_isolation(self):
        """Verify TenantManager.for_store strictly isolates records."""
        store1_medicines = Medicine.objects.for_store(self.store1)
        store2_medicines = Medicine.objects.for_store(self.store2)

        self.assertIn(self.med1, store1_medicines)
        self.assertNotIn(self.med2, store1_medicines)

        self.assertIn(self.med2, store2_medicines)
        self.assertNotIn(self.med1, store2_medicines)

    def test_soft_delete_functionality(self):
        """Verify soft deletion hides items from default queryset but preserves them in DB."""
        self.med1.delete()
        self.assertFalse(self.med1.is_active)
        
        # Excluded from default manager
        self.assertNotIn(self.med1, Medicine.objects.all())
        
        # Included in all_objects
        self.assertIn(self.med1, Medicine.all_objects.all())

        # Restoration
        self.med1.restore()
        self.assertTrue(self.med1.is_active)
        self.assertIn(self.med1, Medicine.objects.all())

    def test_tenant_access_mixin_scopes_queryset(self):
        """Verify CBV automatically restricts queryset to user's assigned store."""
        request = self.factory.get('/fake-url/')
        request.user = self.store1_admin
        
        view = DummyStoreView()
        view.request = request
        qs = view.get_queryset()

        self.assertIn(self.med1, qs)
        self.assertNotIn(self.med2, qs)

    def test_super_admin_cannot_access_store_data_view(self):
        """Rule 1 check: Super admin is blocked from accessing store-specific views."""
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware
        
        request = self.factory.get('/fake-url/')
        request.user = self.super_admin
        
        # Enable sessions and messages for the dummy request
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        setattr(request, '_messages', FallbackStorage(request))

        view = DummyStoreView.as_view()
        response = view(request)
        
        # Should redirect with message and NOT display store data
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/super-admin/', response.url)


class SearchSuggestionsViewTests(TestCase):
    def setUp(self):
        from django.test import Client
        from billing.services import create_invoice
        from inventory.models import MasterMedicine

        self.client = Client()

        self.store1 = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="9876543210", email="apollo@example.com",
            address="Connaught Place", city="New Delhi", state="Delhi", pincode="110001"
        )
        self.store1_admin = User.objects.create_user(
            username="apollo_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store1
        )

        self.store2 = Store.objects.create(
            name="MedPlus Pharmacy", code="MED02", license_number="DL-02",
            phone="9123456789", email="medplus@example.com",
            address="Bandra", city="Mumbai", state="Maharashtra", pincode="400050"
        )

        self.superadmin = User.objects.create_superuser(
            username="superadmin", email="super@example.com", password="password123",
            role=User.Role.SUPER_ADMIN
        )

        self.unit1 = Unit.objects.create(name="Strip", short_name="str", store=self.store1)
        self.cat1 = Category.objects.create(name="Analgesics", description="Pain relief", store=self.store1)
        self.med1 = Medicine.objects.create(
            store=self.store1, name="Dolo 650mg", generic_name="Paracetamol",
            sku="DOLO650", unit=self.unit1, category=self.cat1
        )
        self.batch1 = Batch.objects.create(
            store=self.store1, medicine=self.med1, batch_number="B-1",
            expiry_date="2027-01-01", cost_price=10, mrp=20, selling_price=15,
            tax_percentage=5, quantity=100
        )

        self.master_med = MasterMedicine.objects.create(
            name="Azithral 500mg", salt_composition="Azithromycin",
            manufacturer_name="Alembic", category_name="allopathy"
        )

        self.invoice1 = create_invoice(
            store=self.store1, user=self.store1_admin,
            data={'customer_name': "Deepak Gupta", 'customer_phone': "9988776655", 'items': [{'batch_id': self.batch1.id, 'quantity': 2}]}
        )

    def test_suggestions_unauthenticated_blocked(self):
        res = self.client.get('/core/suggestions/?scope=medicines&q=Dolo')
        self.assertEqual(res.status_code, 401)

    def test_suggestions_empty_query(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get('/core/suggestions/?scope=medicines&q=')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['suggestions'], [])

    def test_medicine_suggestions_scoped_to_store(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get('/core/suggestions/?scope=medicines&q=Dolo')
        self.assertEqual(res.status_code, 200)
        data = res.json()['suggestions']
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]['value'], 'Dolo 650mg')
        self.assertIn('Paracetamol', data[0]['subtitle'])
        self.assertIn('Stock: 98', data[0]['badge'])

    def test_master_catalog_suggestions(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get('/core/suggestions/?scope=master_catalog&q=Azith')
        self.assertEqual(res.status_code, 200)
        data = res.json()['suggestions']
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]['value'], 'Azithral 500mg')

    def test_store_suggestions_superadmin_only(self):
        # Store admin cannot search stores scope
        self.client.login(username="apollo_admin", password="password123")
        res_store_admin = self.client.get('/core/suggestions/?scope=stores&q=Apollo')
        self.assertEqual(res_store_admin.json()['suggestions'], [])

        # Superadmin can search stores
        self.client.login(username="superadmin", password="password123")
        res_super = self.client.get('/core/suggestions/?scope=stores&q=Apollo')
        data = res_super.json()['suggestions']
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]['value'], 'Apollo Pharmacy')

    def test_invoice_suggestions(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get(f'/core/suggestions/?scope=invoices&q=Deepak')
        self.assertEqual(res.status_code, 200)
        data = res.json()['suggestions']
        self.assertTrue(len(data) >= 1)
        self.assertEqual(data[0]['value'], self.invoice1.invoice_number)
        self.assertIn('Deepak Gupta', data[0]['title'])


from io import BytesIO
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import PlatformSetting


class PlatformBrandingSettingsTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username="super_brand_boss", password="password123",
            role=User.Role.SUPER_ADMIN
        )
        self.store = Store.objects.create(
            name="Test Store", code="TST01", license_number="DL-TST",
            phone="1234567890", email="test@store.com",
            address="Addr", city="City", state="State", pincode="110001"
        )
        self.store_admin = User.objects.create_user(
            username="regular_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store
        )

    def _create_test_image(self):
        file = BytesIO()
        image = Image.new('RGBA', size=(100, 100), color=(45, 104, 240, 255))
        image.save(file, 'png')
        file.name = 'test_logo.png'
        file.seek(0)
        return SimpleUploadedFile('test_logo.png', file.read(), content_type='image/png')

    def test_default_platform_setting(self):
        settings = PlatformSetting.get_settings()
        self.assertEqual(settings.brand_name, 'Azmed')
        self.assertFalse(bool(settings.logo_icon))

    def test_super_admin_can_access_settings_page(self):
        self.client.login(username="super_brand_boss", password="password123")
        res = self.client.get('/core/settings/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Platform & Branding Settings")

    def test_store_admin_forbidden_from_settings_page(self):
        self.client.login(username="regular_admin", password="password123")
        res = self.client.get('/core/settings/')
        self.assertIn(res.status_code, [302, 403])

    def test_update_brand_name_and_logo(self):
        self.client.login(username="super_brand_boss", password="password123")
        test_img = self._create_test_image()

        res = self.client.post('/core/settings/', {
            'brand_name': 'Azme',
            'tagline': 'Fast, Reliable Healthcare',
            'logo_icon': test_img
        })
        self.assertEqual(res.status_code, 302)

        settings = PlatformSetting.get_settings()
        self.assertEqual(settings.brand_name, 'Azme')
        self.assertEqual(settings.tagline, 'Fast, Reliable Healthcare')
        self.assertTrue(bool(settings.logo_icon))

        # Logout to access login page as guest
        self.client.logout()
        page = self.client.get('/accounts/login/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Login to Azme")


    def test_remove_logo_resets_to_none(self):
        self.client.login(username="super_brand_boss", password="password123")
        test_img = self._create_test_image()
        self.client.post('/core/settings/', {
            'brand_name': 'Azme',
            'tagline': 'Custom Tag',
            'logo_icon': test_img
        })

        # Now remove logo
        res = self.client.post('/core/settings/', {
            'brand_name': 'Azme',
            'tagline': 'Custom Tag',
            'remove_logo': '1'
        })
        self.assertEqual(res.status_code, 302)

        settings = PlatformSetting.get_settings()
        self.assertFalse(bool(settings.logo_icon))

    def test_login_footer_display_and_customization(self):
        self.client.login(username="super_brand_boss", password="password123")
        res = self.client.post('/core/settings/', {
            'brand_name': 'Azmed',
            'tagline': 'Healthcare',
            'footer_text': '© 2026 Custom Brand Footer Inc.',
            'footer_contact_info': 'Helpline: 1800-AZMED-CARE',
            'show_login_footer': '1',
        })
        self.assertEqual(res.status_code, 302)

        settings = PlatformSetting.get_settings()
        self.assertTrue(settings.show_login_footer)
        self.assertEqual(settings.footer_text, '© 2026 Custom Brand Footer Inc.')
        self.assertEqual(settings.footer_contact_info, 'Helpline: 1800-AZMED-CARE')

        # Check that login page displays this footer
        self.client.logout()
        page = self.client.get('/accounts/login/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "© 2026 Custom Brand Footer Inc.")
        self.assertContains(page, "Helpline: 1800-AZMED-CARE")

    def test_login_footer_toggle_disabled(self):
        self.client.login(username="super_brand_boss", password="password123")
        # Post without show_login_footer
        res = self.client.post('/core/settings/', {
            'brand_name': 'Azmed',
            'tagline': 'Healthcare',
            'footer_text': 'Hidden Copyright Line',
        })
        self.assertEqual(res.status_code, 302)

        settings = PlatformSetting.get_settings()
        self.assertFalse(settings.show_login_footer)

        # Check that login page hides footer
        self.client.logout()
        page = self.client.get('/accounts/login/')
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Hidden Copyright Line")


