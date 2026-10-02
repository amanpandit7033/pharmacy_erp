from django import forms
from stores.models import Store

INPUT_CLASSES = 'w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition bg-white'
CHECKBOX_CLASSES = 'w-4 h-4 text-[#283891] rounded border-slate-300 focus:ring-[#283891]'


class StoreForm(forms.ModelForm):
    # Optional Primary Store Admin Onboarding
    create_store_admin = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES, 'id': 'createStoreAdminToggle'})
    )
    admin_first_name = forms.CharField(
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Rajesh'})
    )
    admin_last_name = forms.CharField(
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Kumar'})
    )
    admin_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'admin@pharmacy.com'})
    )
    admin_phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': '+91 98765 43210'})
    )
    admin_username = forms.CharField(
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. rajesh_care'})
    )
    admin_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'Initial password (min 6 characters)'})
    )

    class Meta:
        model = Store
        fields = [
            'name', 'code', 'logo', 'license_number', 'gst_number',
            'phone', 'email', 'address', 'city', 'state', 'pincode', 'currency',
            'upi_id', 'upi_payee_name', 'is_active',
            'whatsapp_service_type', 'whatsapp_api_key'
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
            'upi_id': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. pharmacy@okhdfcbank'}),
            'upi_payee_name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Apollo Pharmacy'}),
            'is_active': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
            'whatsapp_service_type': forms.Select(attrs={'class': INPUT_CLASSES, 'id': 'whatsappServiceTypeSelect'}),
            'whatsapp_api_key': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'Enter Client WABA Bearer API Key', 'id': 'whatsappApiKeyInput'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        create_admin = cleaned_data.get('create_store_admin')

        # Only validate admin fields if creating a store and checkbox is checked
        if not self.instance.pk and create_admin:
            username = (cleaned_data.get('admin_username') or '').strip()
            email = (cleaned_data.get('admin_email') or '').strip()
            password = cleaned_data.get('admin_password')

            if not username:
                self.add_error('admin_username', 'Username is required to create the administrator account.')
            else:
                from accounts.models import User
                if User.objects.filter(username__iexact=username).exists():
                    self.add_error('admin_username', f"Username '{username}' is already in use. Please pick another.")

            if not email:
                self.add_error('admin_email', 'Email address is required to deliver onboarding login credentials.')

            if not password:
                self.add_error('admin_password', 'Initial password is required for the new administrator.')
            elif len(password) < 6:
                self.add_error('admin_password', 'Password must be at least 6 characters.')

        return cleaned_data


class StoreSettingsForm(forms.ModelForm):
    remove_logo = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Store
        fields = [
            'name', 'logo', 'license_number', 'gst_number',
            'phone', 'email', 'address', 'city', 'state', 'pincode', 'currency',
            'upi_id', 'upi_payee_name', 'whatsapp_service_type', 'whatsapp_api_key'
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
            'upi_id': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. store@okhdfcbank, merchant@upi'}),
            'upi_payee_name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'e.g. Apollo MedPlus Pharmacy'}),
            'whatsapp_service_type': forms.Select(attrs={'class': INPUT_CLASSES, 'id': 'whatsappServiceTypeSelect'}),
            'whatsapp_api_key': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'Enter Client WABA Bearer API Key', 'id': 'whatsappApiKeyInput'}),
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
