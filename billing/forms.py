from django import forms
from billing.models import Expense

INPUT_CLASSES = 'w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition bg-white'


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['title', 'category', 'amount', 'expense_date', 'payment_method', 'paid_to', 'receipt', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. October Shop Rent, Daily Tea & Snacks, Electricity Bill'}),
            'category': forms.Select(attrs={'class': INPUT_CLASSES}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'class': INPUT_CLASSES, 'placeholder': '0.00'}),
            'expense_date': forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASSES}),
            'payment_method': forms.Select(attrs={'class': INPUT_CLASSES}),
            'paid_to': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Landlord, Tea Vendor, Power Corp, Staff Name'}),
            'receipt': forms.ClearableFileInput(attrs={'class': INPUT_CLASSES}),
            'notes': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES, 'placeholder': 'Optional transaction notes, voucher / receipt number, etc.'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = True
        self.fields['amount'].required = True
        self.fields['expense_date'].required = True
