from django.views.generic import ListView, CreateView, UpdateView
from django.views import View
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.db.models import Q

from stores.models import Store
from stores.forms import StoreForm, StoreSettingsForm
from accounts.models import User
from core.mixins import RoleRequiredMixin


class StoreListView(RoleRequiredMixin, ListView):
    model = Store
    template_name = 'stores/store_list.html'
    context_object_name = 'stores'
    allowed_roles = [User.Role.SUPER_ADMIN]
    paginate_by = 15

    def get_queryset(self):
        qs = Store.all_objects.all()
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        state = self.request.GET.get('state', '').strip()
        sort = self.request.GET.get('sort', 'newest').strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(code__icontains=q) |
                Q(city__icontains=q) |
                Q(state__icontains=q) |
                Q(license_number__icontains=q) |
                Q(gst_number__icontains=q) |
                Q(phone__icontains=q) |
                Q(email__icontains=q) |
                Q(pincode__icontains=q)
            )

        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        if state:
            qs = qs.filter(state__iexact=state)

        if sort == 'oldest':
            qs = qs.order_by('created_at', 'id')
        elif sort == 'name_asc':
            qs = qs.order_by('name')
        elif sort == 'name_desc':
            qs = qs.order_by('-name')
        elif sort == 'code':
            qs = qs.order_by('code')
        elif sort == 'city':
            qs = qs.order_by('city', 'name')
        else:  # newest
            qs = qs.order_by('-created_at', '-id')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_qs = Store.all_objects.all()
        context['total_stores_count'] = all_qs.count()
        context['active_stores_count'] = all_qs.filter(is_active=True).count()
        context['inactive_stores_count'] = all_qs.filter(is_active=False).count()
        context['available_states'] = (
            all_qs.exclude(state='').values_list('state', flat=True).distinct().order_by('state')
        )
        return context


class StoreCreateView(RoleRequiredMixin, CreateView):
    model = Store
    form_class = StoreForm
    template_name = 'stores/store_form.html'
    success_url = reverse_lazy('stores:store_list')
    allowed_roles = [User.Role.SUPER_ADMIN]

    def form_valid(self, form):
        messages.success(self.request, f"Store '{form.instance.name}' created successfully.")
        return super().form_valid(form)


class StoreUpdateView(RoleRequiredMixin, UpdateView):
    model = Store
    form_class = StoreForm
    template_name = 'stores/store_form.html'
    success_url = reverse_lazy('stores:store_list')
    allowed_roles = [User.Role.SUPER_ADMIN]

    def get_queryset(self):
        return Store.all_objects.all()

    def form_valid(self, form):
        messages.success(self.request, f"Store '{form.instance.name}' updated successfully.")
        return super().form_valid(form)


class StoreToggleActiveView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        store = get_object_or_404(Store.all_objects.all(), pk=pk)
        store.is_active = not store.is_active
        store.save(update_fields=['is_active'])
        status_str = "activated" if store.is_active else "deactivated"
        messages.success(request, f"Store '{store.name}' has been {status_str}.")
        return redirect('stores:store_list')


class StoreSettingsView(RoleRequiredMixin, UpdateView):
    """Allows Store Admin to view and modify their own store details."""
    model = Store
    form_class = StoreSettingsForm
    template_name = 'stores/store_settings.html'
    success_url = reverse_lazy('stores:settings')
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_object(self, queryset=None):
        return self.request.user.store

    def form_valid(self, form):
        messages.success(self.request, "Store settings saved successfully.")
        return super().form_valid(form)
