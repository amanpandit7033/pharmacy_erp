from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from stores.models import Store
from accounts.models import User
from inventory.models import Category, Unit, Medicine, Batch, MasterMedicine


class InventoryIsolationAndRoleTests(TestCase):
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
            name="MedPlus", code="MED02", license_number="DL-02",
            phone="222", email="m@example.com", address="Addr 2",
            city="Mumbai", state="MH", pincode="400001"
        )
        self.store2_admin = User.objects.create_user(
            username="med_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store2
        )

        # Unit and Medicines
        self.unit1 = Unit.objects.create(store=self.store1, name="Strip", short_name="str")
        self.med1 = Medicine.objects.create(store=self.store1, name="Apollo Aspirin", unit=self.unit1)
        self.batch1 = Batch.objects.create(
            store=self.store1, medicine=self.med1, batch_number="B001",
            expiry_date="2027-01-01", cost_price=Decimal("15.00"),
            mrp=Decimal("30.00"), selling_price=Decimal("25.00"), quantity=50
        )

        self.unit2 = Unit.objects.create(store=self.store2, name="Bottle", short_name="btl")
        self.med2 = Medicine.objects.create(store=self.store2, name="MedPlus Cough Syrup", unit=self.unit2)

    def test_tenant_isolation_in_list(self):
        """Store 1 admin should only see Store 1 medicines."""
        self.client.login(username="apollo_admin", password="password123")
        response = self.client.get(reverse('inventory:medicine_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apollo Aspirin")
        self.assertNotContains(response, "MedPlus Cough Syrup")

    def test_cross_tenant_access_blocked(self):
        """Store 1 admin trying to view Store 2 medicine details gets 404."""
        self.client.login(username="apollo_admin", password="password123")
        response = self.client.get(reverse('inventory:medicine_detail', kwargs={'pk': self.med2.pk}))
        self.assertEqual(response.status_code, 404)

    def test_staff_cannot_view_cost_price(self):
        """Staff can view medicine detail, but purchase cost price is hidden."""
        self.client.login(username="apollo_staff", password="password123")
        response = self.client.get(reverse('inventory:medicine_detail', kwargs={'pk': self.med1.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apollo Aspirin")
        self.assertContains(response, "25.00")  # Selling price
        self.assertNotContains(response, "Purchase Price (Cost)")
        self.assertNotContains(response, "15.00")  # Cost price is 15.00

    def test_staff_cannot_add_medicine(self):
        """Staff is blocked from accessing medicine create view."""
        self.client.login(username="apollo_staff", password="password123")
        response = self.client.get(reverse('inventory:medicine_create'))
        # RoleRequiredMixin redirects with message
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/staff/', response.url)


class MasterMedicineTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.store = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="111", email="a@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.admin = User.objects.create_user(
            username="apollo_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store
        )
        self.master = MasterMedicine.objects.create(
            name="Augmentin 625 Duo Tablet",
            price=Decimal("223.42"),
            manufacturer_name="Glaxo SmithKline Pharmaceuticals Ltd",
            category_name="allopathy",
            pack_size_label="strip of 10 tablets",
            salt_composition="Amoxycillin (500mg) + Clavulanic Acid (125mg)",
            medicine_desc="Antibiotic for bacterial infections."
        )

    def test_master_catalog_search_api(self):
        self.client.login(username="apollo_admin", password="password123")
        response = self.client.get(reverse('inventory:master_catalog_search') + "?q=Augmentin")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['name'], "Augmentin 625 Duo Tablet")
        self.assertEqual(data['results'][0]['price'], "223.42")

    def test_master_catalog_list_view(self):
        self.client.login(username="apollo_admin", password="password123")
        response = self.client.get(reverse('inventory:master_catalog'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Augmentin 625 Duo Tablet")
        self.assertContains(response, "Glaxo SmithKline")

    def test_import_master_medicine_to_store(self):
        self.client.login(username="apollo_admin", password="password123")
        response = self.client.post(
            reverse('inventory:master_catalog_import', kwargs={'pk': self.master.pk})
        )
        # Should redirect to batch create with MRP prefilled
        self.assertEqual(response.status_code, 302)
        self.assertIn('batches/create', response.url)
        self.assertIn('mrp=223.42', response.url)

        # Check medicine is in store
        med = Medicine.objects.get(store=self.store, name="Augmentin 625 Duo Tablet")
        self.assertEqual(med.generic_name, "Amoxycillin (500mg) + Clavulanic Acid (125mg)")
        self.assertEqual(med.manufacturer.name, "Glaxo SmithKline Pharmaceuticals Ltd")
        self.assertEqual(med.category.name, "Allopathy")

    def test_store_creates_unlisted_medicine_submits_to_super_admin(self):
        """When store admin adds an unlisted medicine, it queues for super admin moderation."""
        self.client.login(username="apollo_admin", password="password123")
        unit = Unit.objects.create(store=self.store, name="Bottle", short_name="btl")
        
        response = self.client.post(reverse('inventory:medicine_create'), {
            'name': 'Novel Cure 500mg',
            'generic_name': 'NewMolecule (500mg)',
            'unit': unit.id,
            'min_stock_level': 10,
            'contribute_to_master': True
        })
        self.assertEqual(response.status_code, 302)

        # Verified in store
        med = Medicine.objects.get(store=self.store, name="Novel Cure 500mg")
        self.assertEqual(med.generic_name, 'NewMolecule (500mg)')

        # Verified queued for moderation
        proposal = MasterMedicine.objects.get(name='Novel Cure 500mg')
        self.assertFalse(proposal.is_approved)
        self.assertEqual(proposal.submission_status, 'pending')
        self.assertEqual(proposal.submitted_by_store, self.store)

        # Must not be visible in public search yet
        api_res = self.client.get(reverse('inventory:master_catalog_search') + "?q=Novel Cure")
        self.assertEqual(len(api_res.json()['results']), 0)

        # Super Admin approves it
        superadmin = User.objects.create_user(
            username="superboss", password="password123", role=User.Role.SUPER_ADMIN
        )
        self.client.login(username="superboss", password="password123")
        approve_res = self.client.post(reverse('inventory:master_contribution_approve', kwargs={'pk': proposal.pk}))
        self.assertEqual(approve_res.status_code, 302)

        proposal.refresh_from_db()
        self.assertTrue(proposal.is_approved)
        self.assertEqual(proposal.submission_status, 'approved')

        # Now visible in public search for all stores
        api_res2 = self.client.get(reverse('inventory:master_catalog_search') + "?q=Novel Cure")
        self.assertEqual(len(api_res2.json()['results']), 1)

    def test_super_admin_can_edit_master_medicine(self):
        superadmin = User.objects.create_user(
            username="super_editor", password="password123", role=User.Role.SUPER_ADMIN
        )
        self.client.login(username="super_editor", password="password123")
        response = self.client.post(
            reverse('inventory:master_medicine_edit', kwargs={'pk': self.master.pk}),
            {
                'name': 'Augmentin 625 Duo Forte Tablet',
                'price': '250.00',
                'manufacturer_name': 'GSK Pharma',
                'salt_composition': 'Amoxycillin (500mg) + Clavulanic Acid (125mg)',
                'is_approved': True
            }
        )
        self.assertEqual(response.status_code, 302)
        self.master.refresh_from_db()
        self.assertEqual(self.master.name, 'Augmentin 625 Duo Forte Tablet')
        self.assertEqual(self.master.price, Decimal('250.00'))

    def test_super_admin_can_delete_master_medicine(self):
        superadmin = User.objects.create_user(
            username="super_deleter", password="password123", role=User.Role.SUPER_ADMIN
        )
        self.client.login(username="super_deleter", password="password123")
        response = self.client.post(
            reverse('inventory:master_medicine_delete', kwargs={'pk': self.master.pk})
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MasterMedicine.objects.filter(pk=self.master.pk).exists())

    def test_non_super_admin_cannot_edit_or_delete_master_medicine(self):
        self.client.login(username="apollo_admin", password="password123")
        edit_res = self.client.post(
            reverse('inventory:master_medicine_edit', kwargs={'pk': self.master.pk}),
            {'name': 'Hacked Med'}
        )
        self.assertEqual(edit_res.status_code, 302)
        self.master.refresh_from_db()
        self.assertNotEqual(self.master.name, 'Hacked Med')

        del_res = self.client.post(
            reverse('inventory:master_medicine_delete', kwargs={'pk': self.master.pk})
        )
        self.assertEqual(del_res.status_code, 302)
        self.assertTrue(MasterMedicine.objects.filter(pk=self.master.pk).exists())


class CategoryAndUnitCRUDTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.store1 = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="111", email="a@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.store1_admin = User.objects.create_user(
            username="apollo_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store1
        )
        self.store2 = Store.objects.create(
            name="MedPlus", code="MED02", license_number="DL-02",
            phone="222", email="m@example.com", address="Addr 2",
            city="Mumbai", state="MH", pincode="400001"
        )
        self.store2_admin = User.objects.create_user(
            username="med_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store2
        )

        self.cat1 = Category.objects.create(store=self.store1, name="Antibiotics", description="Bacterial treatment")
        self.cat2 = Category.objects.create(store=self.store2, name="Cardiology", description="Heart medications")

        self.unit1 = Unit.objects.create(store=self.store1, name="Strip", short_name="str")
        self.unit2 = Unit.objects.create(store=self.store2, name="Bottle", short_name="btl")

        self.med1 = Medicine.objects.create(store=self.store1, name="Amoxicillin 500", category=self.cat1, unit=self.unit1)

    def test_category_list_tenant_isolation(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get(reverse('inventory:category_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Antibiotics")
        self.assertNotContains(res, "Cardiology")

    def test_category_create(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:category_create'), {
            'name': 'Painkillers',
            'description': 'Analgesics'
        })
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Category.objects.filter(store=self.store1, name='Painkillers').exists())

    def test_category_edit(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:category_edit', kwargs={'pk': self.cat1.pk}), {
            'name': 'Antibiotics & Antimicrobials',
            'description': 'Updated description'
        })
        self.assertEqual(res.status_code, 302)
        self.cat1.refresh_from_db()
        self.assertEqual(self.cat1.name, 'Antibiotics & Antimicrobials')

    def test_category_delete_unlinks_medicine(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:category_delete', kwargs={'pk': self.cat1.pk}))
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Category.objects.filter(pk=self.cat1.pk).exists())
        self.med1.refresh_from_db()
        self.assertIsNone(self.med1.category)

    def test_unit_list_tenant_isolation(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get(reverse('inventory:unit_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Strip")
        self.assertNotContains(res, "Bottle")

    def test_unit_create(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:unit_create'), {
            'name': 'Box',
            'short_name': 'bx'
        })
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Unit.objects.filter(store=self.store1, name='Box').exists())

    def test_unit_edit(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:unit_edit', kwargs={'pk': self.unit1.pk}), {
            'name': 'Blister Strip',
            'short_name': 'blst'
        })
        self.assertEqual(res.status_code, 302)
        self.unit1.refresh_from_db()
        self.assertEqual(self.unit1.name, 'Blister Strip')
        self.assertEqual(self.unit1.short_name, 'blst')

    def test_unit_delete_blocked_when_medicines_assigned(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:unit_delete', kwargs={'pk': self.unit1.pk}))
        self.assertEqual(res.status_code, 302)
        # Unit should still exist because med1 is assigned to it
        self.assertTrue(Unit.objects.filter(pk=self.unit1.pk).exists())

    def test_unit_delete_success_when_no_medicines_assigned(self):
        self.client.login(username="apollo_admin", password="password123")
        empty_unit = Unit.objects.create(store=self.store1, name="Vial", short_name="vl")
        res = self.client.post(reverse('inventory:unit_delete', kwargs={'pk': empty_unit.pk}))
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Unit.objects.filter(pk=empty_unit.pk).exists())

    def test_cross_tenant_edit_delete_prevented(self):
        self.client.login(username="apollo_admin", password="password123")
        # Attempt to edit Store 2's category
        res = self.client.get(reverse('inventory:category_edit', kwargs={'pk': self.cat2.pk}))
        self.assertEqual(res.status_code, 404)

        # Attempt to delete Store 2's category
        res = self.client.post(reverse('inventory:category_delete', kwargs={'pk': self.cat2.pk}))
        self.assertEqual(res.status_code, 404)

        # Attempt to edit Store 2's unit
        res = self.client.get(reverse('inventory:unit_edit', kwargs={'pk': self.unit2.pk}))
        self.assertEqual(res.status_code, 404)

        # Attempt to delete Store 2's unit
        res = self.client.post(reverse('inventory:unit_delete', kwargs={'pk': self.unit2.pk}))
        self.assertEqual(res.status_code, 404)


class ProductAndStockCRUDTests(TestCase):
    def setUp(self):
        self.client = Client()
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

        self.store2 = Store.objects.create(
            name="MedPlus", code="MED02", license_number="DL-02",
            phone="222", email="m@example.com", address="Addr 2",
            city="Mumbai", state="MH", pincode="400001"
        )
        self.store2_admin = User.objects.create_user(
            username="med_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store2
        )

        self.unit1 = Unit.objects.create(store=self.store1, name="Strip", short_name="str")
        self.med1 = Medicine.objects.create(
            store=self.store1, name="Metformin 500mg", generic_name="Metformin Hydrochloride",
            unit=self.unit1
        )
        self.batch1 = Batch.objects.create(
            store=self.store1, medicine=self.med1, batch_number="MET001",
            expiry_date="2027-06-30", cost_price=Decimal("10.00"),
            mrp=Decimal("25.00"), selling_price=Decimal("20.00"), quantity=100
        )

        self.unit2 = Unit.objects.create(store=self.store2, name="Bottle", short_name="btl")
        self.med2 = Medicine.objects.create(
            store=self.store2, name="MedPlus Syrup", unit=self.unit2
        )
        self.batch2 = Batch.objects.create(
            store=self.store2, medicine=self.med2, batch_number="SYR002",
            expiry_date="2026-12-31", cost_price=Decimal("40.00"),
            mrp=Decimal("80.00"), selling_price=Decimal("70.00"), quantity=50
        )

    def test_store_admin_can_edit_medicine(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:medicine_edit', kwargs={'pk': self.med1.pk}), {
            'name': 'Metformin 500mg SR',
            'generic_name': 'Metformin HCl Sustained Release',
            'unit': self.unit1.pk,
            'min_stock_level': 15,
        })
        self.assertEqual(res.status_code, 302)
        self.med1.refresh_from_db()
        self.assertEqual(self.med1.name, 'Metformin 500mg SR')
        self.assertEqual(self.med1.min_stock_level, 15)

    def test_store_admin_can_delete_medicine_and_batches(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:medicine_delete', kwargs={'pk': self.med1.pk}))
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('inventory:medicine_list'))

        # Medicine and its batches should now be inactive
        self.assertFalse(Medicine.objects.filter(pk=self.med1.pk).exists())
        self.assertFalse(Batch.objects.filter(pk=self.batch1.pk).exists())

    def test_store_admin_can_edit_batch(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:batch_edit', kwargs={'pk': self.batch1.pk}), {
            'batch_number': 'MET001-MOD',
            'expiry_date': '2027-12-31',
            'cost_price': '12.00',
            'mrp': '30.00',
            'selling_price': '24.00',
            'tax_percentage': '5.00',
            'quantity': 150
        })
        self.assertEqual(res.status_code, 302)
        self.batch1.refresh_from_db()
        self.assertEqual(self.batch1.batch_number, 'MET001-MOD')
        self.assertEqual(self.batch1.quantity, 150)
        self.assertEqual(self.batch1.selling_price, Decimal('24.00'))

    def test_store_admin_can_delete_batch(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.post(reverse('inventory:batch_delete', kwargs={'pk': self.batch1.pk}))
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('inventory:medicine_detail', kwargs={'pk': self.med1.pk}))

        # Batch is soft-deleted, but medicine remains intact
        self.assertFalse(Batch.objects.filter(pk=self.batch1.pk).exists())
        self.assertTrue(Medicine.objects.filter(pk=self.med1.pk).exists())

    def test_staff_cannot_delete_medicine_or_batch(self):
        self.client.login(username="apollo_staff", password="password123")
        med_res = self.client.post(reverse('inventory:medicine_delete', kwargs={'pk': self.med1.pk}))
        self.assertEqual(med_res.status_code, 302)
        self.assertTrue(Medicine.objects.filter(pk=self.med1.pk).exists())

        batch_res = self.client.post(reverse('inventory:batch_delete', kwargs={'pk': self.batch1.pk}))
        self.assertEqual(batch_res.status_code, 302)
        self.assertTrue(Batch.objects.filter(pk=self.batch1.pk).exists())

    def test_cross_tenant_medicine_and_batch_isolation(self):
        self.client.login(username="apollo_admin", password="password123")
        # Attempt to edit Store 2's medicine
        res = self.client.get(reverse('inventory:medicine_edit', kwargs={'pk': self.med2.pk}))
        self.assertEqual(res.status_code, 404)

        # Attempt to delete Store 2's medicine
        res = self.client.post(reverse('inventory:medicine_delete', kwargs={'pk': self.med2.pk}))
        self.assertEqual(res.status_code, 404)

        # Attempt to edit Store 2's batch
        res = self.client.get(reverse('inventory:batch_edit', kwargs={'pk': self.batch2.pk}))
        self.assertEqual(res.status_code, 404)

        # Attempt to delete Store 2's batch
        res = self.client.post(reverse('inventory:batch_delete', kwargs={'pk': self.batch2.pk}))
        self.assertEqual(res.status_code, 404)


class ListViewFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.store = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="111", email="a@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.admin = User.objects.create_user(
            username="apollo_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store
        )
        self.cat1 = Category.objects.create(store=self.store, name="Analgesics")
        self.cat2 = Category.objects.create(store=self.store, name="Vitamins")
        self.unit = Unit.objects.create(store=self.store, name="Strip", short_name="str")

        # Create two medicines: med1 first, then med2
        self.med1 = Medicine.objects.create(
            store=self.store, name="Alpha Aspirin", category=self.cat1, unit=self.unit,
            is_prescription_required=False, min_stock_level=10
        )
        self.med2 = Medicine.objects.create(
            store=self.store, name="Beta Brufen", category=self.cat1, unit=self.unit,
            is_prescription_required=True, min_stock_level=5
        )

        # Batch for med1: 50 units (in stock)
        Batch.objects.create(
            store=self.store, medicine=self.med1, batch_number="B1",
            expiry_date="2027-01-01", cost_price=Decimal("10"), mrp=Decimal("20"),
            selling_price=Decimal("18"), quantity=50
        )
        # med2 has NO batch (0 units, out of stock)

    def test_medicine_list_shows_latest_added_first_by_default(self):
        self.client.login(username="apollo_admin", password="password123")
        res = self.client.get(reverse('inventory:medicine_list'))
        self.assertEqual(res.status_code, 200)
        medicines = list(res.context['medicines'])
        # med2 was created after med1, so med2 must be first in the list
        self.assertEqual(medicines[0].pk, self.med2.pk)
        self.assertEqual(medicines[1].pk, self.med1.pk)

    def test_medicine_list_stock_filters(self):
        self.client.login(username="apollo_admin", password="password123")
        # In stock: med1 only
        res_in = self.client.get(reverse('inventory:medicine_list') + '?stock=in_stock')
        self.assertEqual(res_in.status_code, 200)
        self.assertEqual(len(res_in.context['medicines']), 1)
        self.assertEqual(res_in.context['medicines'][0].pk, self.med1.pk)

        # Out of stock: med2 only
        res_out = self.client.get(reverse('inventory:medicine_list') + '?stock=out_of_stock')
        self.assertEqual(res_out.status_code, 200)
        self.assertEqual(len(res_out.context['medicines']), 1)
        self.assertEqual(res_out.context['medicines'][0].pk, self.med2.pk)

    def test_medicine_list_rx_filter(self):
        self.client.login(username="apollo_admin", password="password123")
        # Rx only: med2
        res = self.client.get(reverse('inventory:medicine_list') + '?rx=rx')
        self.assertEqual(len(res.context['medicines']), 1)
        self.assertEqual(res.context['medicines'][0].pk, self.med2.pk)

        # OTC only: med1
        res_otc = self.client.get(reverse('inventory:medicine_list') + '?rx=otc')
        self.assertEqual(len(res_otc.context['medicines']), 1)
        self.assertEqual(res_otc.context['medicines'][0].pk, self.med1.pk)

    def test_medicine_list_sorting(self):
        self.client.login(username="apollo_admin", password="password123")
        # Name A-Z: Alpha Aspirin first
        res = self.client.get(reverse('inventory:medicine_list') + '?sort=name_asc')
        self.assertEqual(res.context['medicines'][0].pk, self.med1.pk)

        # Name Z-A: Beta Brufen first
        res_desc = self.client.get(reverse('inventory:medicine_list') + '?sort=name_desc')
        self.assertEqual(res_desc.context['medicines'][0].pk, self.med2.pk)

    def test_category_list_filters(self):
        self.client.login(username="apollo_admin", password="password123")
        # Search filter
        res = self.client.get(reverse('inventory:category_list') + '?q=Analgesics')
        self.assertEqual(len(res.context['categories']), 1)
        self.assertEqual(res.context['categories'][0].pk, self.cat1.pk)

        # Usage filter: 'used' (cat1 has medicines), 'empty' (cat2 has 0)
        res_used = self.client.get(reverse('inventory:category_list') + '?usage=used')
        self.assertEqual(len(res_used.context['categories']), 1)
        self.assertEqual(res_used.context['categories'][0].pk, self.cat1.pk)

        res_empty = self.client.get(reverse('inventory:category_list') + '?usage=empty')
        self.assertEqual(len(res_empty.context['categories']), 1)
        self.assertEqual(res_empty.context['categories'][0].pk, self.cat2.pk)

    def test_unit_list_filters(self):
        self.client.login(username="apollo_admin", password="password123")
        empty_unit = Unit.objects.create(store=self.store, name="Vial", short_name="vl")

        res_used = self.client.get(reverse('inventory:unit_list') + '?usage=used')
        self.assertEqual(len(res_used.context['units']), 1)
        self.assertEqual(res_used.context['units'][0].pk, self.unit.pk)

        res_empty = self.client.get(reverse('inventory:unit_list') + '?usage=empty')
        self.assertEqual(len(res_empty.context['units']), 1)
        self.assertEqual(res_empty.context['units'][0].pk, empty_unit.pk)


from django.core.files.uploadedfile import SimpleUploadedFile

class MasterCatalogImportExportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.super_admin = User.objects.create_superuser(
            username="super_hero", email="super@example.com", password="password123",
            role=User.Role.SUPER_ADMIN
        )
        self.store = Store.objects.create(
            name="Apollo Pharmacy", code="APL01", license_number="DL-01",
            phone="111", email="a@example.com", address="Addr 1",
            city="Delhi", state="Delhi", pincode="110001"
        )
        self.store_admin = User.objects.create_user(
            username="store_boss", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store
        )

        self.med1 = MasterMedicine.objects.create(
            name="Augmentin 625 Duo",
            price=Decimal("204.50"),
            manufacturer_name="GSK",
            category_name="allopathy",
            salt_composition="Amoxycillin + Clavulanic Acid",
            is_approved=True
        )
        self.med2 = MasterMedicine.objects.create(
            name="Liv 52 Syrup",
            price=Decimal("150.00"),
            manufacturer_name="Himalaya",
            category_name="ayurvedic",
            salt_composition="Herbal extract",
            is_approved=True
        )

    def test_export_catalog_super_admin(self):
        self.client.login(username="super_hero", password="password123")
        res = self.client.get(reverse('inventory:master_catalog_export'))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res['Content-Type'].startswith('text/csv'))
        content = b"".join(res.streaming_content).decode('utf-8-sig')
        self.assertIn("Augmentin 625 Duo", content)
        self.assertIn("Liv 52 Syrup", content)
        self.assertIn("Amoxycillin + Clavulanic Acid", content)

    def test_export_catalog_filtered(self):
        self.client.login(username="super_hero", password="password123")
        res = self.client.get(reverse('inventory:master_catalog_export') + '?category=ayurvedic')
        self.assertEqual(res.status_code, 200)
        content = b"".join(res.streaming_content).decode('utf-8-sig')
        self.assertIn("Liv 52 Syrup", content)
        self.assertNotIn("Augmentin 625 Duo", content)

    def test_sample_csv_download(self):
        self.client.login(username="super_hero", password="password123")
        res = self.client.get(reverse('inventory:master_catalog_sample_csv'))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res['Content-Type'].startswith('text/csv'))
        content = res.content.decode('utf-8-sig')
        self.assertIn("Paracetamol 500mg Tablet", content)
        self.assertIn("Augmentin 625 Duo Tablet", content)

    def test_import_csv_create_and_update(self):
        self.client.login(username="super_hero", password="password123")
        csv_content = (
            "name,price,manufacturer_name,category_name,pack_size_label,salt_composition\n"
            "Augmentin 625 Duo,215.00,GlaxoSmithKline,allopathy,strip of 10 tablets,Amoxycillin (500mg) + Clavulanate (125mg)\n"
            "Dolo 650mg,32.00,Micro Labs,allopathy,strip of 15 tablets,Paracetamol (650mg)\n"
        ).encode('utf-8')
        uploaded = SimpleUploadedFile("catalog.csv", csv_content, content_type="text/csv")

        res = self.client.post(reverse('inventory:master_catalog_import_csv'), {
            'csv_file': uploaded,
            'duplicate_mode': 'update',
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        # Check existing updated
        self.med1.refresh_from_db()
        self.assertEqual(self.med1.price, Decimal("215.00"))
        self.assertEqual(self.med1.manufacturer_name, "GlaxoSmithKline")

        # Check new created
        dolo = MasterMedicine.objects.get(name="Dolo 650mg")
        self.assertEqual(dolo.price, Decimal("32.00"))
        self.assertEqual(dolo.category_name, "allopathy")
        self.assertTrue(dolo.is_approved)

    def test_import_csv_skip_duplicates(self):
        self.client.login(username="super_hero", password="password123")
        csv_content = (
            "name,price,manufacturer_name\n"
            "Augmentin 625 Duo,999.00,Fake Pharma\n"
            "New Med Unique,45.00,Sun Pharma\n"
        ).encode('utf-8')
        uploaded = SimpleUploadedFile("catalog.csv", csv_content, content_type="text/csv")

        res = self.client.post(reverse('inventory:master_catalog_import_csv'), {
            'csv_file': uploaded,
            'duplicate_mode': 'skip',
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        # med1 should NOT be updated
        self.med1.refresh_from_db()
        self.assertEqual(self.med1.price, Decimal("204.50"))
        self.assertEqual(self.med1.manufacturer_name, "GSK")

        # new med created
        self.assertTrue(MasterMedicine.objects.filter(name="New Med Unique").exists())

    def test_store_admin_forbidden_from_master_import_export(self):
        self.client.login(username="store_boss", password="password123")
        res_export = self.client.get(reverse('inventory:master_catalog_export'))
        self.assertEqual(res_export.status_code, 302)
        self.assertRedirects(res_export, reverse('dashboard:store_admin_dashboard'))

        res_import = self.client.get(reverse('inventory:master_catalog_import_csv'))
        self.assertEqual(res_import.status_code, 302)
        self.assertRedirects(res_import, reverse('dashboard:store_admin_dashboard'))

        res_sample = self.client.get(reverse('inventory:master_catalog_sample_csv'))
        self.assertEqual(res_sample.status_code, 302)
        self.assertRedirects(res_sample, reverse('dashboard:store_admin_dashboard'))


class ExpiryWatchlistAndQuarantineTests(TestCase):
    def setUp(self):
        self.store = Store.objects.create(name="HealthCare Pharmacy", code="HCP01")
        self.admin = User.objects.create_user(
            username="hcp_admin", password="password123",
            role=User.Role.STORE_ADMIN, store=self.store
        )
        self.staff = User.objects.create_user(
            username="hcp_staff", password="password123",
            role=User.Role.STAFF, store=self.store
        )
        self.category = Category.objects.create(store=self.store, name="Antibiotics")
        self.unit = Unit.objects.create(store=self.store, name="Strip", short_name="str")
        self.med = Medicine.objects.create(
            store=self.store, name="Amoxicillin 500mg", category=self.category, unit=self.unit,
            min_stock_level=10
        )

        today = timezone.now().date()
        # Expired batch
        self.batch_expired = Batch.objects.create(
            store=self.store, medicine=self.med, batch_number="EXP001",
            expiry_date=today - timezone.timedelta(days=5),
            cost_price=Decimal("40.00"), mrp=Decimal("70.00"), selling_price=Decimal("65.00"),
            quantity=20
        )
        # 15 days left (Critical <= 30d)
        self.batch_critical = Batch.objects.create(
            store=self.store, medicine=self.med, batch_number="CRT015",
            expiry_date=today + timezone.timedelta(days=15),
            cost_price=Decimal("45.00"), mrp=Decimal("75.00"), selling_price=Decimal("70.00"),
            quantity=30
        )
        # 45 days left (31-60d)
        self.batch_warning = Batch.objects.create(
            store=self.store, medicine=self.med, batch_number="WRN045",
            expiry_date=today + timezone.timedelta(days=45),
            cost_price=Decimal("50.00"), mrp=Decimal("80.00"), selling_price=Decimal("75.00"),
            quantity=40
        )
        # Fresh batch (180 days left)
        self.batch_fresh = Batch.objects.create(
            store=self.store, medicine=self.med, batch_number="FRS180",
            expiry_date=today + timezone.timedelta(days=180),
            cost_price=Decimal("50.00"), mrp=Decimal("80.00"), selling_price=Decimal("75.00"),
            quantity=100
        )

    def test_total_stock_excludes_quarantined_batches(self):
        # Initial active stock: 20 + 30 + 40 + 100 = 190
        self.assertEqual(self.med.total_stock, 190)

        # Quarantine critical batch
        self.batch_critical.quarantine(user=self.admin, reason="Damaged foil")
        self.batch_critical.refresh_from_db()
        self.assertEqual(self.batch_critical.status, Batch.Status.QUARANTINED)
        self.assertEqual(self.batch_critical.quarantine_reason, "Damaged foil")
        self.assertEqual(self.batch_critical.quarantined_by, self.admin)
        self.assertIsNotNone(self.batch_critical.quarantined_at)

        # Now med total stock should exclude the 30 units: 190 - 30 = 160
        self.assertEqual(self.med.total_stock, 160)

    def test_quarantine_action_view_post(self):
        self.client.login(username="hcp_admin", password="password123")
        url = reverse('inventory:batch_quarantine_action', kwargs={'pk': self.batch_warning.pk})
        
        # 1. Post Quarantine
        res = self.client.post(url, {
            'action': 'quarantine',
            'reason': 'Quality check',
            'next': reverse('inventory:expiry_watch')
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.batch_warning.refresh_from_db()
        self.assertTrue(self.batch_warning.is_quarantined)

        # 2. Post Release
        res = self.client.post(url, {
            'action': 'release',
            'next': reverse('inventory:expiry_watch')
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.batch_warning.refresh_from_db()
        self.assertEqual(self.batch_warning.status, Batch.Status.ACTIVE)

        # 3. Post Dispose
        res = self.client.post(url, {
            'action': 'dispose',
            'reason': 'Biomedical waste incinerator',
            'next': reverse('inventory:expiry_watch')
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.batch_warning.refresh_from_db()
        self.assertTrue(self.batch_warning.is_disposed)

    def test_cannot_release_expired_batch_from_quarantine(self):
        self.client.login(username="hcp_admin", password="password123")
        # First quarantine the expired batch
        self.batch_expired.quarantine(user=self.admin, reason="Already expired")
        url = reverse('inventory:batch_quarantine_action', kwargs={'pk': self.batch_expired.pk})
        
        # Attempt to release
        res = self.client.post(url, {'action': 'release'}, follow=True)
        self.assertEqual(res.status_code, 200)
        self.batch_expired.refresh_from_db()
        # Should remain quarantined
        self.assertTrue(self.batch_expired.is_quarantined)

    def test_expiry_watch_list_view_and_filtering(self):
        self.client.login(username="hcp_admin", password="password123")
        
        # Default view (all risk: expired, <= 90 days, quarantined)
        res = self.client.get(reverse('inventory:expiry_watch'))
        self.assertEqual(res.status_code, 200)
        batch_ids = [b.id for b in res.context['batches']]
        self.assertIn(self.batch_expired.id, batch_ids)
        self.assertIn(self.batch_critical.id, batch_ids)
        self.assertIn(self.batch_warning.id, batch_ids)
        self.assertNotIn(self.batch_fresh.id, batch_ids)  # 180 days is not at risk

        # Filter: Expired only
        res_exp = self.client.get(reverse('inventory:expiry_watch'), {'timeframe': 'expired'})
        self.assertEqual(res_exp.status_code, 200)
        exp_ids = [b.id for b in res_exp.context['batches']]
        self.assertIn(self.batch_expired.id, exp_ids)
        self.assertNotIn(self.batch_critical.id, exp_ids)

        # Filter: 30 days only
        res_30 = self.client.get(reverse('inventory:expiry_watch'), {'timeframe': '30'})
        self.assertEqual(res_30.status_code, 200)
        ids_30 = [b.id for b in res_30.context['batches']]
        self.assertIn(self.batch_critical.id, ids_30)
        self.assertNotIn(self.batch_expired.id, ids_30)

    def test_expiry_watch_export_csv(self):
        self.client.login(username="hcp_admin", password="password123")
        res = self.client.get(reverse('inventory:expiry_watch_export'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')
        content = res.content.decode('utf-8')
        self.assertIn("Medicine Name", content)
        self.assertIn("Amoxicillin 500mg", content)
        self.assertIn("EXP001", content)
        self.assertIn("CRT015", content)







