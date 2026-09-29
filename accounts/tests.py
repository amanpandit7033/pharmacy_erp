from django.test import TestCase
from django.core.exceptions import ValidationError
from django.urls import reverse
from stores.models import Store
from accounts.models import User


class UserModelTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(
            name="Apollo Meds",
            code="APL01",
            license_number="DL-12345",
            phone="9876543210",
            email="apollo@example.com",
            address="123 Health Ave",
            city="New Delhi",
            state="Delhi",
            pincode="110001"
        )

    def test_create_super_admin_success(self):
        user = User.objects.create_user(
            username="superadmin",
            password="securepassword",
            role=User.Role.SUPER_ADMIN
        )
        user.full_clean()
        self.assertTrue(user.is_super_admin)
        self.assertFalse(user.is_store_admin)
        self.assertFalse(user.is_staff_member)
        self.assertIsNone(user.store)

    def test_super_admin_cannot_have_store(self):
        user = User(
            username="bad_superadmin",
            password="securepassword",
            role=User.Role.SUPER_ADMIN,
            store=self.store
        )
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_create_store_admin_success(self):
        user = User.objects.create_user(
            username="storeadmin",
            password="securepassword",
            role=User.Role.STORE_ADMIN,
            store=self.store
        )
        user.full_clean()
        self.assertFalse(user.is_super_admin)
        self.assertTrue(user.is_store_admin)
        self.assertFalse(user.is_staff_member)
        self.assertEqual(user.store, self.store)

    def test_store_admin_requires_store(self):
        user = User(
            username="storeadmin_nostore",
            password="securepassword",
            role=User.Role.STORE_ADMIN,
            store=None
        )
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_staff_member_requires_store(self):
        user = User(
            username="staff_nostore",
            password="securepassword",
            role=User.Role.STAFF,
            store=None
        )
        with self.assertRaises(ValidationError):
            user.full_clean()


class StoreAdminManagementTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(
            name="Apollo Pharmacy",
            code="APL01",
            license_number="DL-11111",
            phone="9876543210",
            email="apollo@example.com",
            address="123 Health Ave",
            city="New Delhi",
            state="Delhi",
            pincode="110001"
        )
        self.superadmin = User.objects.create_user(
            username="superadmin",
            password="SuperPassword123",
            role=User.Role.SUPER_ADMIN
        )
        self.store_admin = User.objects.create_user(
            username="test_store_admin",
            password="OldPassword123",
            role=User.Role.STORE_ADMIN,
            store=self.store,
            first_name="John",
            last_name="Doe",
            email="john@apollo.com"
        )

    def test_super_admin_can_access_edit_page(self):
        self.client.login(username="superadmin", password="SuperPassword123")
        url = reverse('accounts:store_admin_edit', kwargs={'pk': self.store_admin.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "test_store_admin")
        self.assertContains(response, "Update Password")

    def test_super_admin_can_update_profile_without_changing_password(self):
        self.client.login(username="superadmin", password="SuperPassword123")
        url = reverse('accounts:store_admin_edit', kwargs={'pk': self.store_admin.pk})
        data = {
            'store': self.store.pk,
            'first_name': 'Johnny',
            'last_name': 'Updated',
            'email': 'johnny@apollo.com',
            'phone': '9998887776',
            'is_active': 'on',
            'new_password': ''  # blank = keep existing
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.store_admin.refresh_from_db()
        self.assertEqual(self.store_admin.first_name, 'Johnny')
        self.assertEqual(self.store_admin.last_name, 'Updated')
        self.assertEqual(self.store_admin.phone, '9998887776')
        self.assertTrue(self.store_admin.check_password('OldPassword123'))

    def test_super_admin_can_update_store_admin_password(self):
        self.client.login(username="superadmin", password="SuperPassword123")
        url = reverse('accounts:store_admin_edit', kwargs={'pk': self.store_admin.pk})
        data = {
            'store': self.store.pk,
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@apollo.com',
            'phone': '9876543210',
            'is_active': 'on',
            'new_password': 'BrandNewPassword@999'
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.store_admin.refresh_from_db()
        self.assertTrue(self.store_admin.check_password('BrandNewPassword@999'))
        self.assertFalse(self.store_admin.check_password('OldPassword123'))

        # Verify store admin can now log in with the new password
        self.client.logout()
        login_success = self.client.login(username="test_store_admin", password="BrandNewPassword@999")
        self.assertTrue(login_success)

    def test_store_admin_list_has_edit_action(self):
        self.client.login(username="superadmin", password="SuperPassword123")
        url = reverse('accounts:store_admin_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        edit_url = reverse('accounts:store_admin_edit', kwargs={'pk': self.store_admin.pk})
        self.assertContains(response, edit_url)
        self.assertContains(response, "Edit & Password")
        self.assertContains(response, "Login As")

    def test_super_admin_can_impersonate_store_admin_without_password(self):
        self.client.login(username="superadmin", password="SuperPassword123")
        impersonate_url = reverse('accounts:impersonate_user', kwargs={'pk': self.store_admin.pk})

        # Post to impersonate
        response = self.client.post(impersonate_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/role-redirect/', response.url)

        # Follow to dashboard
        dash_response = self.client.get(response.url, follow=True)
        self.assertEqual(dash_response.status_code, 200)

        # Current user in session should now be store_admin
        self.assertEqual(dash_response.context['request'].user.pk, self.store_admin.pk)
        self.assertEqual(self.client.session.get('impersonator_id'), self.superadmin.pk)

        # Impersonation banner should be visible
        self.assertContains(dash_response, "IMPERSONATION ACTIVE")
        self.assertContains(dash_response, "Exit & Return to Super Admin")

        # Now exit impersonation
        exit_url = reverse('accounts:exit_impersonation')
        exit_response = self.client.post(exit_url, follow=True)
        self.assertEqual(exit_response.status_code, 200)

        # Current user should be back to superadmin
        self.assertEqual(exit_response.context['request'].user.pk, self.superadmin.pk)
        self.assertNotIn('impersonator_id', self.client.session)

    def test_non_super_admin_cannot_impersonate(self):
        self.client.login(username="test_store_admin", password="OldPassword123")
        impersonate_url = reverse('accounts:impersonate_user', kwargs={'pk': self.superadmin.pk})
        response = self.client.post(impersonate_url)
        # Blocked by RoleRequiredMixin
        self.assertEqual(response.status_code, 302)
        # Still logged in as store admin
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.store_admin.pk))


class StoreAdminListViewFilterTests(TestCase):
    def setUp(self):
        self.store1 = Store.objects.create(
            name="Apollo Meds", code="APL01", license_number="DL-111",
            phone="111", email="a@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.store2 = Store.objects.create(
            name="Care Chemist", code="CARE02", license_number="DL-222",
            phone="222", email="c@example.com", address="Addr 2",
            city="Pune", state="Maharashtra", pincode="411001"
        )
        self.superadmin = User.objects.create_superuser(
            username="superboss", email="super@azmed.com", password="password123",
            role=User.Role.SUPER_ADMIN
        )
        self.admin1 = User.objects.create_user(
            username="rajesh_apollo", first_name="Rajesh", last_name="Sharma",
            email="rajesh@apollo.com", phone="9876500001", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store1, is_active=True
        )
        self.admin2 = User.objects.create_user(
            username="anita_care", first_name="Anita", last_name="Deshmukh",
            email="anita@care.com", phone="9876500002", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store2, is_active=False
        )

    def test_search_by_username_and_email(self):
        self.client.login(username="superboss", password="password123")
        res = self.client.get(reverse('accounts:store_admin_list') + '?q=rajesh')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['store_admins']), 1)
        self.assertEqual(res.context['store_admins'][0].pk, self.admin1.pk)

        res_email = self.client.get(reverse('accounts:store_admin_list') + '?q=care.com')
        self.assertEqual(len(res_email.context['store_admins']), 1)
        self.assertEqual(res_email.context['store_admins'][0].pk, self.admin2.pk)

    def test_filter_by_status(self):
        self.client.login(username="superboss", password="password123")
        res_active = self.client.get(reverse('accounts:store_admin_list') + '?status=active')
        self.assertEqual(len(res_active.context['store_admins']), 1)
        self.assertEqual(res_active.context['store_admins'][0].pk, self.admin1.pk)

        res_inactive = self.client.get(reverse('accounts:store_admin_list') + '?status=inactive')
        self.assertEqual(len(res_inactive.context['store_admins']), 1)
        self.assertEqual(res_inactive.context['store_admins'][0].pk, self.admin2.pk)

    def test_filter_by_store(self):
        self.client.login(username="superboss", password="password123")
        res_store = self.client.get(reverse('accounts:store_admin_list') + f'?store={self.store1.id}')
        self.assertEqual(len(res_store.context['store_admins']), 1)
        self.assertEqual(res_store.context['store_admins'][0].pk, self.admin1.pk)

    def test_sort_by_username(self):
        self.client.login(username="superboss", password="password123")
        res_asc = self.client.get(reverse('accounts:store_admin_list') + '?sort=username_asc')
        self.assertEqual(res_asc.context['store_admins'][0].pk, self.admin2.pk)  # anita first

        res_desc = self.client.get(reverse('accounts:store_admin_list') + '?sort=username_desc')
        self.assertEqual(res_desc.context['store_admins'][0].pk, self.admin1.pk)  # rajesh first



