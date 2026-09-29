import csv
import os
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from inventory.models import MasterMedicine


class Command(BaseCommand):
    help = "Imports Indian medicine master database from updated_indian_medicine_data.csv"

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=str(settings.BASE_DIR / 'updated_indian_medicine_data.csv'),
            help='Path to the CSV file'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of records to import (for quick testing)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing MasterMedicine records before importing'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=2000,
            help='Batch size for bulk_create'
        )

    def handle(self, *args, **options):
        file_path = options['file']
        limit = options['limit']
        clear_first = options['clear']
        batch_size = options['batch_size']

        if not os.path.exists(file_path):
            self.stderr.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        if clear_first:
            self.stdout.write("Clearing existing MasterMedicine records...")
            MasterMedicine.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("MasterMedicine table cleared."))

        self.stdout.write(f"Starting import from: {file_path}")
        if limit:
            self.stdout.write(f"Limiting to first {limit} records.")

        total_imported = 0
        batch = []

        try:
            with open(file_path, mode='r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.DictReader(f)
                
                with transaction.atomic():
                    for row in reader:
                        name = (row.get('name') or '').strip()
                        if not name:
                            continue

                        # Clean price
                        raw_price = (row.get('price') or '').strip()
                        try:
                            price = Decimal(raw_price) if raw_price else Decimal('0.00')
                        except (InvalidOperation, ValueError):
                            price = Decimal('0.00')

                        is_disc = (row.get('Is_discontinued') or '').strip().upper() == 'TRUE'
                        mfg = (row.get('manufacturer_name') or '').strip()
                        cat = (row.get('type') or '').strip()
                        pack = (row.get('pack_size_label') or '').strip()
                        s1 = (row.get('short_composition1') or '').strip()
                        s2 = (row.get('short_composition2') or '').strip()
                        salt = (row.get('salt_composition') or '').strip()
                        if not salt:
                            salt = " + ".join(filter(None, [s1, s2]))

                        desc = (row.get('medicine_desc') or '').strip()
                        side_fx = (row.get('side_effects') or '').strip()
                        interactions = (row.get('drug_interactions') or '').strip()

                        obj = MasterMedicine(
                            name=name[:255],
                            price=price,
                            is_discontinued=is_disc,
                            manufacturer_name=mfg[:255],
                            category_name=cat[:100],
                            pack_size_label=pack[:150],
                            short_composition1=s1[:255],
                            short_composition2=s2[:255],
                            salt_composition=salt,
                            medicine_desc=desc,
                            side_effects=side_fx,
                            drug_interactions=interactions,
                        )
                        batch.append(obj)

                        if len(batch) >= batch_size:
                            MasterMedicine.objects.bulk_create(batch)
                            total_imported += len(batch)
                            batch = []
                            self.stdout.write(f"Imported {total_imported} records...")

                        if limit and (total_imported + len(batch)) >= limit:
                            break

                    if batch:
                        MasterMedicine.objects.bulk_create(batch)
                        total_imported += len(batch)
                        batch = []

            self.stdout.write(self.style.SUCCESS(f"Successfully imported {total_imported} master medicines!"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error importing medicines: {e}"))
            raise e
