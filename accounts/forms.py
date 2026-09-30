from django import forms
from django.contrib.auth.forms import AuthenticationForm
from accounts.models import User

INPUT_CLASSES = 'w-full px-3.5 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition bg-white'
CHECKBOX_CLASSES = 'w-4 h-4 text-[#283891] rounded border-slate-300 focus:ring-[#283891]'


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition',
            'placeholder': 'Enter your username',
            'autocomplete': 'username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 focus:border-[#283891] focus:ring-2 focus:ring-[#283891]/10 text-xs text-slate-800 font-medium outline-none transition',
            'placeholder': 'Enter your password',
            'autocomplete': 'current-password'
        })
    )


class StaffCreationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Initial password'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
        }

    def __init__(self, *args, store=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = store
        if store:
            self.instance.store = store
        self.instance.role = User.Role.STAFF

    def clean(self):
        cleaned_data = super().clean()
        if self.store:
            self.instance.store = self.store
        self.instance.role = User.Role.STAFF
        if not self.instance.store:
            raise forms.ValidationError("Store administrator must be assigned to an active pharmacy store to add staff.")
        return cleaned_data

    def _post_clean(self):
        if self.store:
            self.instance.store = self.store
        self.instance.role = User.Role.STAFF
        super()._post_clean()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.role = User.Role.STAFF
        user.store = self.store
        if commit:
            user.save()
        return user


class StaffUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'is_active': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
        }


class StoreAdminCreationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Initial password'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'store', 'first_name', 'last_name', 'email', 'phone', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'store': forms.Select(attrs={'class': INPUT_CLASSES}),
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.role = User.Role.STORE_ADMIN
        if commit:
            user.save()
        return user


class StoreAdminUpdateForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Enter new password to reset (leave blank to keep current)',
            'autocomplete': 'new-password'
        }),
        label="Reset Password"
    )

    class Meta:
        model = User
        fields = ['store', 'first_name', 'last_name', 'email', 'phone', 'is_active']
        widgets = {
            'store': forms.Select(attrs={'class': INPUT_CLASSES}),
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'is_active': forms.CheckboxInput(attrs={'class': CHECKBOX_CLASSES}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        new_password = self.cleaned_data.get('new_password')
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASSES}),
            'email': forms.EmailInput(attrs={'class': INPUT_CLASSES}),
            'phone': forms.TextInput(attrs={'class': INPUT_CLASSES}),
        }
