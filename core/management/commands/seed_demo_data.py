from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import User
from stores.models import Store
from inventory.models import Category, Unit, Medicine, Batch
from billing.services import create_invoice


class Command(BaseCommand):
    help = "Seeds comprehensive demo data for Multi-tenant Pharmacy Billing Software."

    def handle(self, *args, **options):
        self.stdout.write("Starting demo data population...")

        # 1. Super Admin
        super_admin, created = User.objects.get_or_create(
            username="superadmin",
            defaults={
                'email': "superadmin@pharmaflow.local",
                'role': User.Role.SUPER_ADMIN,
                'first_name': "Platform",
                'last_name': "SuperAdmin",
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            super_admin.set_password("admin123")
            super_admin.save()
            self.stdout.write(self.style.SUCCESS("[OK] Created Super Admin (user: superadmin, pass: admin123)"))
        else:
            self.stdout.write("Super Admin already exists.")

        # 2. Store 1: Apollo Pharmacy
        store1, _ = Store.all_objects.get_or_create(
            code="APL01",
            defaults={
                'name': "Apollo Pharmacy & Healthcare",
                'license_number': "DL-APL-2024-99881",
                'gst_number': "07AAAAA0000A1Z5",
                'phone': "+91 98111 22233",
                'email': "apollo.delhi@example.com",
                'address': "Plot 12, Connaught Place",
                'city': "New Delhi",
                'state': "Delhi",
                'pincode': "110001",
                'currency': "₹",
                'is_active': True,
            }
        )

        store1_admin, created = User.objects.get_or_create(
            username="apollo_admin",
            defaults={
                'email': "manager@apollo-delhi.com",
                'role': User.Role.STORE_ADMIN,
                'store': store1,
                'first_name': "Rajesh",
                'last_name': "Sharma",
                'phone': "9811122234",
            }
        )
        if created:
            store1_admin.set_password("apollo123")
            store1_admin.save()
            self.stdout.write(self.style.SUCCESS("[OK] Created Apollo Store Admin (user: apollo_admin, pass: apollo123)"))

        store1_staff, created = User.objects.get_or_create(
            username="apollo_staff",
            defaults={
                'email': "staff@apollo-delhi.com",
                'role': User.Role.STAFF,
                'store': store1,
                'first_name': "Amit",
                'last_name': "Verma",
                'phone': "9811122235",
            }
        )
        if created:
            store1_staff.set_password("staff123")
            store1_staff.save()
            self.stdout.write(self.style.SUCCESS("[OK] Created Apollo Staff (user: apollo_staff, pass: staff123)"))

        # Categories & Units for Store 1
        cat_antibiotic, _ = Category.objects.get_or_create(store=store1, name="Antibiotics", defaults={'description': "Bacterial infection treatments"})
        cat_pain, _ = Category.objects.get_or_create(store=store1, name="Pain Relief & Analgesics", defaults={'description': "Fever and inflammation"})
        cat_cardio, _ = Category.objects.get_or_create(store=store1, name="Cardiovascular", defaults={'description': "Blood pressure and heart care"})

        unit_strip, _ = Unit.objects.get_or_create(store=store1, name="Strip (10 Tablets)", defaults={'short_name': "str"})
        unit_bottle, _ = Unit.objects.get_or_create(store=store1, name="Bottle", defaults={'short_name': "btl"})

        # Medicines & Batches for Store 1
        med1, _ = Medicine.objects.get_or_create(
            store=store1,
            name="Amoxicillin 500mg",
            defaults={
                'generic_name': "Amoxicillin Trihydrate",
                'category': cat_antibiotic,
                'unit': unit_strip,
                'rack_location': "A-01-RACK",
                'min_stock_level': 15,
                'is_prescription_required': True
            }
        )
        Batch.objects.get_or_create(
            store=store1,
            medicine=med1,
            batch_number="AMX-2026-B1",
            defaults={
                'expiry_date': timezone.now().date() + timezone.timedelta(days=365),
                'cost_price': Decimal('45.00'),
                'mrp': Decimal('85.00'),
                'selling_price': Decimal('75.00'),
                'tax_percentage': Decimal('12.00'),
                'quantity': 100
            }
        )

        med2, _ = Medicine.objects.get_or_create(
            store=store1,
            name="Dolo 650mg",
            defaults={
                'generic_name': "Paracetamol 650mg",
                'category': cat_pain,
                'unit': unit_strip,
                'rack_location': "B-03-RACK",
                'min_stock_level': 20,
                'is_prescription_required': False
            }
        )
        b2, _ = Batch.objects.get_or_create(
            store=store1,
            medicine=med2,
            batch_number="DL-650-99",
            defaults={
                'expiry_date': timezone.now().date() + timezone.timedelta(days=45), # Near expiry!
                'cost_price': Decimal('18.50'),
                'mrp': Decimal('32.00'),
                'selling_price': Decimal('30.00'),
                'tax_percentage': Decimal('5.00'),
                'quantity': 80
            }
        )

        med3, _ = Medicine.objects.get_or_create(
            store=store1,
            name="Telmisartan 40mg",
            defaults={
                'generic_name': "Telmisartan",
                'category': cat_cardio,
                'unit': unit_strip,
                'rack_location': "C-02-RACK",
                'min_stock_level': 10,
                'is_prescription_required': True
            }
        )
        Batch.objects.get_or_create(
            store=store1,
            medicine=med3,
            batch_number="TEL-40-101",
            defaults={
                'expiry_date': timezone.now().date() + timezone.timedelta(days=420),
                'cost_price': Decimal('60.00'),
                'mrp': Decimal('110.00'),
                'selling_price': Decimal('98.00'),
                'tax_percentage': Decimal('12.00'),
                'quantity': 50
            }
        )

        # Create a sample billed invoice for Apollo
        if b2.quantity > 5:
            try:
                create_invoice(
                    store=store1,
                    user=store1_staff,
                    data={
                        'customer_name': "Rohan Gupta",
                        'customer_phone': "9899988877",
                        'doctor_name': "Dr. K. Mehta (MD)",
                        'payment_method': "UPI",
                        'discount_amount': Decimal('5.00'),
                        'notes': "First time visit",
                        'items': [
                            {'batch_id': b2.id, 'quantity': 2, 'unit_price': b2.selling_price, 'tax_percentage': b2.tax_percentage}
                        ]
                    }
                )
                self.stdout.write(self.style.SUCCESS("[OK] Generated sample initial bill for Apollo Pharmacy"))
            except Exception as e:
                self.stdout.write(f"Sample invoice note: {e}")

        # 3. Store 2: CarePlus Meds (Demonstrating Tenant Isolation)
        store2, _ = Store.all_objects.get_or_create(
            code="CPM02",
            defaults={
                'name': "CarePlus Meds & Diagnostic",
                'license_number': "DL-CPM-2024-55112",
                'gst_number': "27BBBBB1111B1Z9",
                'phone': "+91 99222 33344",
                'email': "careplus.mumbai@example.com",
                'address': "Shop 4, Bandra West",
                'city': "Mumbai",
                'state': "Maharashtra",
                'pincode': "400050",
                'currency': "₹",
                'is_active': True,
            }
        )

        store2_admin, created = User.objects.get_or_create(
            username="careplus_admin",
            defaults={
                'email': "manager@careplus-mumbai.com",
                'role': User.Role.STORE_ADMIN,
                'store': store2,
                'first_name': "Priya",
                'last_name': "Deshmukh",
                'phone': "9922233345",
            }
        )
        if created:
            store2_admin.set_password("careplus123")
            store2_admin.save()
            self.stdout.write(self.style.SUCCESS("[OK] Created CarePlus Store Admin (user: careplus_admin, pass: careplus123)"))

        store2_staff, created = User.objects.get_or_create(
            username="careplus_staff",
            defaults={
                'email': "staff@careplus-mumbai.com",
                'role': User.Role.STAFF,
                'store': store2,
                'first_name': "Siddharth",
                'last_name': "Patil",
                'phone': "9922233346",
            }
        )
        if created:
            store2_staff.set_password("staff123")
            store2_staff.save()
            self.stdout.write(self.style.SUCCESS("[OK] Created CarePlus Staff (user: careplus_staff, pass: staff123)"))

        cat_supplements, _ = Category.objects.get_or_create(store=store2, name="Supplements & Nutrition")
        unit_bottle2, _ = Unit.objects.get_or_create(store=store2, name="Bottle", defaults={'short_name': "btl"})

        med_store2, _ = Medicine.objects.get_or_create(
            store=store2,
            name="Vitamin C 1000mg Effervescent",
            defaults={
                'generic_name': "Ascorbic Acid + Zinc",
                'category': cat_supplements,
                'unit': unit_bottle2,
                'rack_location': "FRONT-SHELF-1",
                'min_stock_level': 10,
                'is_prescription_required': False
            }
        )
        Batch.objects.get_or_create(
            store=store2,
            medicine=med_store2,
            batch_number="VTC-MUM-01",
            defaults={
                'expiry_date': timezone.now().date() + timezone.timedelta(days=200),
                'cost_price': Decimal('140.00'),
                'mrp': Decimal('280.00'),
                'selling_price': Decimal('250.00'),
                'tax_percentage': Decimal('18.00'),
                'quantity': 60
            }
        )

        self.stdout.write(self.style.SUCCESS("\n[OK] Demo data successfully seeded!"))
        self.stdout.write("\nCredentials:")
        self.stdout.write("1. Super Admin: superadmin / admin123")
        self.stdout.write("2. Apollo Store Admin: apollo_admin / apollo123")
        self.stdout.write("3. Apollo Staff: apollo_staff / staff123")
        self.stdout.write("4. CarePlus Store Admin: careplus_admin / careplus123")
        self.stdout.write("5. CarePlus Staff: careplus_staff / staff123")
