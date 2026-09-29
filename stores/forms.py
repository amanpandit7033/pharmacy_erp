from django import forms
from stores.models import Store

INPUT_CLASSES = 'w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition bg-white'
CHECKBOX_CLASSES = 'w-4 h-4 text-[#283891] rounded border-slate-300 focus:ring-[#283891]'


class StoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = [
            'name', 'code', 'logo', 'license_number', 'gst_number',
            'phone', 'email', 'address', 'city', 'state', 'pincode', 'currency', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'code': forms.TextInput(attrs={'class': INPUT_CLASSES + ' uppercase'}),
            'license_number': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'gst_number': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'address': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES}),
            'city': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'state': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'pincode': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'currency': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'is_active': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
        }


class StoreSettingsForm(forms.ModelForm):
    remove_logo = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Store
        fields = [
            'name', 'logo', 'license_number', 'gst_number',
            'phone', 'email', 'address', 'city', 'state', 'pincode', 'currency'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'license_number': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'gst_number': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'address': forms.Textarea(attrs={'rows': 2, 'class': INPUT_CLASSES}),
            'city': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'state': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'pincode': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'currency': forms.TextInput(attrs={'class': INPUT_CLASSES}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and hasattr(logo, 'size'):
            if logo.size > 3 * 1024 * 1024:
                raise forms.ValidationError("Store logo image cannot exceed 3 MB.")
        return logo

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('remove_logo'):
            if instance.logo:
                instance.logo.delete(save=False)
            instance.logo = None
        if commit:
            instance.save()
        return instance
