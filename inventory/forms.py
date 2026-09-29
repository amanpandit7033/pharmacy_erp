from django import forms
from inventory.models import Medicine, Batch, Category, Manufacturer, Unit, MasterMedicine

INPUT_CLASSES = 'w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition bg-white'
CHECKBOX_CLASSES = 'w-4 h-4 text-[#283891] rounded border-slate-300 focus:ring-[#283891]'


class MedicineForm(forms.ModelForm):
    class Meta:
        model = Medicine
        fields = [
            'name', 'generic_name', 'category', 'manufacturer', 'unit',
            'sku', 'rack_location', 'min_stock_level', 'is_prescription_required', 'description'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'generic_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'category': forms.Select(attrs={'class': INPUT_CLASSES}),
            'manufacturer': forms.Select(attrs={'class': INPUT_CLASSES}),
            'unit': forms.Select(attrs={'class': INPUT_CLASSES}),
            'sku': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'rack_location': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Shelf A-3'}),
            'min_stock_level': forms.NumberInput(attrs={'class': INPUT_CLASSES}),
            'is_prescription_required': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES}),
        }

    contribute_to_master = forms.BooleanField(
        required=False,
        initial=True,
        label="Submit to National Master Catalog",
        help_text="Submit this new medicine for Super Admin review so it becomes available to all branches nationwide.",
        widget=forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES})
    )

    def __init__(self, *args, store=None, **kwargs):
        super().__init__(*args, **kwargs)
        if store:
            self.fields['category'].queryset = Category.objects.filter(store=store)
            self.fields['manufacturer'].queryset = Manufacturer.objects.filter(store=store)
            self.fields['unit'].queryset = Unit.objects.filter(store=store)


class BatchForm(forms.ModelForm):
    class Meta:
        model = Batch
        fields = [
            'batch_number', 'manufacturing_date', 'expiry_date',
            'cost_price', 'mrp', 'selling_price', 'tax_percentage', 'quantity',
            'status', 'quarantine_reason'
        ]
        widgets = {
            'batch_number': forms.TextInput(attrs={'class': INPUT_CLASSES + ' uppercase font-mono'}),
            'manufacturing_date': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASSES}),
            'expiry_date': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASSES}),
            'cost_price': forms.NumberInput(attrs={'step': '0.01', 'class': INPUT_CLASSES}),
            'mrp': forms.NumberInput(attrs={'step': '0.01', 'class': INPUT_CLASSES}),
            'selling_price': forms.NumberInput(attrs={'step': '0.01', 'class': INPUT_CLASSES}),
            'tax_percentage': forms.NumberInput(attrs={'step': '0.01', 'class': INPUT_CLASSES}),
            'quantity': forms.NumberInput(attrs={'class': INPUT_CLASSES}),
            'status': forms.Select(attrs={'class': INPUT_CLASSES}),
            'quarantine_reason': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'Optional reason if quarantined, disposed, or returned'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'status' in self.fields:
            self.fields['status'].required = False
            if not self.instance.pk and not self.initial.get('status'):
                self.fields['status'].initial = Batch.Status.ACTIVE

    def clean_status(self):
        return self.cleaned_data.get('status') or (self.instance.status if self.instance.pk else Batch.Status.ACTIVE)


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Antibiotics, Pain Relief'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES, 'placeholder': 'Optional description of the therapeutic category...'}),
        }


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['name', 'short_name']
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Strip, Bottle, Box'}),
            'short_name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. str, btl, box'}),
        }


class MasterMedicineForm(forms.ModelForm):
    class Meta:
        model = MasterMedicine
        fields = [
            'name', 'price', 'manufacturer_name', 'category_name',
            'pack_size_label', 'salt_composition', 'is_discontinued',
            'is_approved', 'medicine_desc', 'side_effects', 'drug_interactions'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'price': forms.NumberInput(attrs={'step': '0.01', 'class': INPUT_CLASSES}),
            'manufacturer_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'category_name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Allopathy, Ayurvedic, Homeopathy'}),
            'pack_size_label': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. strip of 10 tablets, bottle of 100 ml'}),
            'salt_composition': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES, 'placeholder': 'Active chemical salts and strengths'}),
            'is_discontinued': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
            'is_approved': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
            'medicine_desc': forms.Textarea(attrs={'rows': 3, 'class': INPUT_CLASSES}),
            'side_effects': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES}),
            'drug_interactions': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES}),
        }

