import csv
import io
from decimal import Decimal, InvalidOperation

from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum, Count, F, Value
from django.db.models.functions import Coalesce, Greatest
from django.contrib.postgres.search import TrigramSimilarity, TrigramWordSimilarity
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone

from inventory.models import Medicine, Batch, Category, Unit, Manufacturer, MasterMedicine, Supplier
from inventory.forms import MedicineForm, BatchForm, CategoryForm, UnitForm, MasterMedicineForm, SupplierForm
from accounts.models import User
from core.mixins import RoleRequiredMixin, TenantAccessMixin


class MedicineListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    model = Medicine
    template_name = 'inventory/medicine_list.html'
    context_object_name = 'medicines'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]
    paginate_by = 20

    def get_paginate_by(self, queryset):
        per_page = self.request.GET.get('per_page', '').strip()
        if per_page in ['10', '20', '50', '100', '200']:
            return int(per_page)
        return 20

    def get_queryset(self):
        qs = super().get_queryset().select_related('category', 'unit', 'manufacturer').prefetch_related('batches')
        # Annotate total active stock quantity for DB-level filtering and sorting
        qs = qs.annotate(
            total_qty=Coalesce(
                Sum('batches__quantity', filter=Q(batches__is_active=True, batches__status=Batch.Status.ACTIVE)),
                Value(0)
            )
        )

        q = self.request.GET.get('q', '').strip()
        cat = self.request.GET.get('category', '').strip()
        unit_id = self.request.GET.get('unit', '').strip()
        stock_filter = self.request.GET.get('stock', '').strip()
        rx_filter = self.request.GET.get('rx', '').strip()
        sort_by = self.request.GET.get('sort', 'latest').strip()

        self.is_fuzzy_search = False
        self.suggested_medicine = ''

        if q:
            q_clean = q.strip('. -_')
            exact_filter = (
                Q(name__icontains=q) |
                Q(generic_name__icontains=q) |
                Q(sku__icontains=q) |
                Q(rack_location__icontains=q)
            )
            if q_clean and q_clean != q:
                exact_filter |= (
                    Q(name__icontains=q_clean) |
                    Q(generic_name__icontains=q_clean) |
                    Q(sku__icontains=q_clean) |
                    Q(rack_location__icontains=q_clean)
                )

            exact_qs = qs.filter(exact_filter)
            if exact_qs.exists():
                qs = exact_qs
            else:
                try:
                    search_term = q_clean if q_clean else q
                    fuzzy_qs = qs.annotate(
                        sim_name_word=TrigramWordSimilarity(search_term, 'name'),
                        sim_name_full=TrigramSimilarity('name', search_term),
                        sim_gen=TrigramWordSimilarity(search_term, 'generic_name'),
                    ).annotate(
                        sim_score=Greatest(F('sim_name_word'), F('sim_name_full'), F('sim_gen'))
                    ).filter(
                        sim_score__gte=0.20
                    ).order_by('-sim_score')

                    if fuzzy_qs.exists():
                        self.is_fuzzy_search = True
                        self.suggested_medicine = fuzzy_qs.first().name
                        qs = fuzzy_qs
                    else:
                        qs = exact_qs
                except Exception:
                    qs = exact_qs
        if cat:
            qs = qs.filter(category_id=cat)
        if unit_id:
            qs = qs.filter(unit_id=unit_id)
        if rx_filter == 'rx':
            qs = qs.filter(is_prescription_required=True)
        elif rx_filter == 'otc':
            qs = qs.filter(is_prescription_required=False)

        if stock_filter == 'in_stock':
            qs = qs.filter(total_qty__gt=0)
        elif stock_filter == 'low_stock':
            qs = qs.filter(total_qty__gt=0, total_qty__lte=F('min_stock_level'))
        elif stock_filter == 'out_of_stock':
            qs = qs.filter(total_qty=0)

        # Sorting: Default is latest added medicine first (-created_at, -id)
        if self.is_fuzzy_search and sort_by == 'latest':
            pass  # Retain similarity ranking for typo matches
        elif sort_by == 'oldest':
            qs = qs.order_by('created_at', 'id')
        elif sort_by == 'name_asc':
            qs = qs.order_by('name')
        elif sort_by == 'name_desc':
            qs = qs.order_by('-name')
        elif sort_by == 'stock_high':
            qs = qs.order_by('-total_qty', '-created_at', '-id')
        elif sort_by == 'stock_low':
            qs = qs.order_by('total_qty', '-created_at', '-id')
        else:  # 'latest' default
            qs = qs.order_by('-created_at', '-id')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store
        context['categories'] = Category.objects.filter(store=store).order_by('name')
        context['units'] = Unit.objects.filter(store=store).order_by('name')
        context['can_manage_stock'] = (self.request.user.role in [User.Role.STORE_ADMIN, User.Role.STAFF])
        context['can_view_cost'] = (self.request.user.role == User.Role.STORE_ADMIN)
        context['total_products_count'] = Medicine.objects.filter(store=store).count()
        context['is_fuzzy_search'] = getattr(self, 'is_fuzzy_search', False)
        context['suggested_medicine'] = getattr(self, 'suggested_medicine', '')
        return context


class MedicineDetailView(TenantAccessMixin, RoleRequiredMixin, DetailView):
    model = Medicine
    template_name = 'inventory/medicine_detail.html'
    context_object_name = 'medicine'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['batches'] = self.object.batches.filter(is_active=True).order_by('expiry_date')
        context['can_manage_stock'] = (self.request.user.role in [User.Role.STORE_ADMIN, User.Role.STAFF])
        context['can_view_cost'] = (self.request.user.role == User.Role.STORE_ADMIN)
        return context


class MedicineCreateView(TenantAccessMixin, RoleRequiredMixin, CreateView):
    model = Medicine
    form_class = MedicineForm
    template_name = 'inventory/medicine_form.html'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.request.user.store
        return kwargs

    def form_valid(self, form):
        form.instance.store = self.request.user.store
        response = super().form_valid(form)
        messages.success(self.request, f"Medicine '{self.object.name}' added successfully to your store.")

        # Check if store opted to contribute to National Master Catalog
        contribute = form.cleaned_data.get('contribute_to_master', True)
        if contribute and self.request.user.store:
            med_name = self.object.name.strip()
            # If not in MasterMedicine
            if not MasterMedicine.objects.filter(name__iexact=med_name).exists():
                MasterMedicine.objects.create(
                    name=med_name,
                    salt_composition=self.object.generic_name.strip() if self.object.generic_name else '',
                    category_name=self.object.category.name if self.object.category else 'Allopathy',
                    pack_size_label=self.object.unit.name if self.object.unit else 'Strip',
                    manufacturer_name=self.object.manufacturer.name if self.object.manufacturer else '',
                    medicine_desc=self.object.description or '',
                    is_approved=False,
                    submission_status='pending',
                    submitted_by_store=self.request.user.store
                )
                messages.info(
                    self.request,
                    f"'{med_name}' has also been submitted to Super Admin for verification and publishing to all branches."
                )

        return response

    def get_success_url(self):
        return reverse('inventory:medicine_detail', kwargs={'pk': self.object.pk})


class MedicineUpdateView(TenantAccessMixin, RoleRequiredMixin, UpdateView):
    model = Medicine
    form_class = MedicineForm
    template_name = 'inventory/medicine_form.html'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.request.user.store
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f"Medicine '{form.instance.name}' updated.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('inventory:medicine_detail', kwargs={'pk': self.object.pk})


class MedicineDeleteView(TenantAccessMixin, RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def post(self, request, pk, *args, **kwargs):
        med = get_object_or_404(Medicine, pk=pk, store=request.user.store)
        name = med.name
        med.batches.update(is_active=False)
        med.delete()
        messages.success(request, f"Product '{name}' and its stock batches have been deleted successfully.")
        return redirect('inventory:medicine_list')


class BatchCreateView(TenantAccessMixin, RoleRequiredMixin, CreateView):
    model = Batch
    form_class = BatchForm
    template_name = 'inventory/batch_form.html'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def dispatch(self, request, *args, **kwargs):
        self.medicine = get_object_or_404(
            Medicine,
            pk=self.kwargs['medicine_pk'],
            store=request.user.store
        )
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if 'mrp' in self.request.GET:
            initial['mrp'] = self.request.GET.get('mrp')
        if 'selling_price' in self.request.GET:
            initial['selling_price'] = self.request.GET.get('selling_price')
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.request.user.store
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['medicine'] = self.medicine
        return context

    def form_valid(self, form):
        form.instance.store = self.request.user.store
        form.instance.medicine = self.medicine
        messages.success(self.request, f"Batch '{form.instance.batch_number}' added for {self.medicine.name}.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('inventory:medicine_detail', kwargs={'pk': self.medicine.pk})


class BatchUpdateView(TenantAccessMixin, RoleRequiredMixin, UpdateView):
    model = Batch
    form_class = BatchForm
    template_name = 'inventory/batch_form.html'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.request.user.store
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['medicine'] = self.object.medicine
        return context

    def form_valid(self, form):
        messages.success(self.request, f"Batch '{form.instance.batch_number}' updated.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('inventory:medicine_detail', kwargs={'pk': self.object.medicine.pk})


class BatchDeleteView(TenantAccessMixin, RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def post(self, request, pk, *args, **kwargs):
        batch = get_object_or_404(Batch, pk=pk, store=request.user.store)
        med = batch.medicine
        batch_number = batch.batch_number
        batch.delete()
        messages.success(request, f"Batch '{batch_number}' deleted successfully.")
        return redirect('inventory:medicine_detail', pk=med.pk)



# Categories & Units Management (Store Admin)
class CategoryListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    model = Category
    template_name = 'inventory/category_list.html'
    context_object_name = 'categories'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]
    paginate_by = 50

    def get_paginate_by(self, queryset):
        per_page = self.request.GET.get('per_page', '').strip()
        if per_page in ['20', '50', '100', '200']:
            return int(per_page)
        return 50

    def get_queryset(self):
        qs = Category.objects.filter(store=self.request.user.store).annotate(
            med_count=Count('medicines', filter=Q(medicines__is_active=True))
        )
        q = self.request.GET.get('q', '').strip()
        usage = self.request.GET.get('usage', '').strip()
        sort = self.request.GET.get('sort', 'name_asc').strip()

        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        if usage == 'used':
            qs = qs.filter(med_count__gt=0)
        elif usage == 'empty':
            qs = qs.filter(med_count=0)

        if sort == 'latest':
            qs = qs.order_by('-created_at')
        elif sort == 'name_desc':
            qs = qs.order_by('-name')
        elif sort == 'med_high':
            qs = qs.order_by('-med_count', 'name')
        elif sort == 'med_low':
            qs = qs.order_by('med_count', 'name')
        else:
            qs = qs.order_by('name')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_categories_count'] = Category.objects.filter(store=self.request.user.store).count()
        return context


class CategoryCreateView(TenantAccessMixin, RoleRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'inventory/category_form.html'
    success_url = reverse_lazy('inventory:category_list')
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def form_valid(self, form):
        form.instance.store = self.request.user.store
        messages.success(self.request, f"Category '{form.instance.name}' created.")
        return super().form_valid(form)


class CategoryUpdateView(TenantAccessMixin, RoleRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'inventory/category_form.html'
    success_url = reverse_lazy('inventory:category_list')
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_queryset(self):
        return Category.objects.filter(store=self.request.user.store)

    def form_valid(self, form):
        messages.success(self.request, f"Category '{form.instance.name}' updated successfully.")
        return super().form_valid(form)


class CategoryDeleteView(TenantAccessMixin, RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        cat = get_object_or_404(Category, pk=pk, store=request.user.store)
        name = cat.name
        cat.medicines.update(category=None)
        cat.delete()
        messages.success(request, f"Category '{name}' deleted successfully.")
        return redirect('inventory:category_list')



class UnitListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    model = Unit
    template_name = 'inventory/unit_list.html'
    context_object_name = 'units'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]
    paginate_by = 50

    def get_paginate_by(self, queryset):
        per_page = self.request.GET.get('per_page', '').strip()
        if per_page in ['20', '50', '100', '200']:
            return int(per_page)
        return 50

    def get_queryset(self):
        qs = Unit.objects.filter(store=self.request.user.store).annotate(
            med_count=Count('medicines', filter=Q(medicines__is_active=True))
        )
        q = self.request.GET.get('q', '').strip()
        usage = self.request.GET.get('usage', '').strip()
        sort = self.request.GET.get('sort', 'name_asc').strip()

        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(short_name__icontains=q))
        if usage == 'used':
            qs = qs.filter(med_count__gt=0)
        elif usage == 'empty':
            qs = qs.filter(med_count=0)

        if sort == 'latest':
            qs = qs.order_by('-created_at')
        elif sort == 'name_desc':
            qs = qs.order_by('-name')
        elif sort == 'med_high':
            qs = qs.order_by('-med_count', 'name')
        elif sort == 'med_low':
            qs = qs.order_by('med_count', 'name')
        else:
            qs = qs.order_by('name')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_units_count'] = Unit.objects.filter(store=self.request.user.store).count()
        return context


class UnitCreateView(TenantAccessMixin, RoleRequiredMixin, CreateView):
    model = Unit
    form_class = UnitForm
    template_name = 'inventory/unit_form.html'
    success_url = reverse_lazy('inventory:unit_list')
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def form_valid(self, form):
        form.instance.store = self.request.user.store
        messages.success(self.request, f"Measurement Unit '{form.instance.name}' created.")
        return super().form_valid(form)


class UnitUpdateView(TenantAccessMixin, RoleRequiredMixin, UpdateView):
    model = Unit
    form_class = UnitForm
    template_name = 'inventory/unit_form.html'
    success_url = reverse_lazy('inventory:unit_list')
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_queryset(self):
        return Unit.objects.filter(store=self.request.user.store)

    def form_valid(self, form):
        messages.success(self.request, f"Measurement Unit '{form.instance.name}' updated successfully.")
        return super().form_valid(form)


class UnitDeleteView(TenantAccessMixin, RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        unit = get_object_or_404(Unit, pk=pk, store=request.user.store)
        med_count = unit.medicines.count()
        if med_count > 0:
            messages.error(
                request,
                f"Cannot delete unit '{unit.name}' because {med_count} medicine(s) are currently using it. Please reassign those medicines first."
            )
            return redirect('inventory:unit_list')

        name = unit.name
        unit.delete()
        messages.success(request, f"Measurement Unit '{name}' deleted successfully.")
        return redirect('inventory:unit_list')


# Supplier & Medicine Procurement Tracking (Store Admin)
class SupplierListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    """
    Store Admin view for managing medicine suppliers and tracking spending.
    """
    model = Supplier
    template_name = 'inventory/supplier_list.html'
    context_object_name = 'suppliers'
    paginate_by = 20
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_queryset(self):
        qs = Supplier.objects.filter(store=self.request.user.store, is_active=True).annotate(
            total_spent=Coalesce(Sum(F('batches__cost_price') * F('batches__quantity'), filter=Q(batches__is_active=True)), Value(Decimal('0.00'))),
            batches_count=Count('batches', filter=Q(batches__is_active=True), distinct=True)
        )
        q = self.request.GET.get('q', '').strip()
        sort = self.request.GET.get('sort', 'name_asc').strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(contact_person__icontains=q) |
                Q(phone__icontains=q) |
                Q(gst_number__icontains=q) |
                Q(dl_number__icontains=q)
            )

        if sort == 'spent_desc':
            qs = qs.order_by('-total_spent', 'name')
        elif sort == 'batches_desc':
            qs = qs.order_by('-batches_count', 'name')
        elif sort == 'latest':
            qs = qs.order_by('-created_at')
        elif sort == 'name_desc':
            qs = qs.order_by('-name')
        else:
            qs = qs.order_by('name')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store
        all_store_suppliers = Supplier.objects.filter(store=store, is_active=True)
        
        # Calculate total procurement spending across all batches linked to suppliers
        total_spent_agg = Batch.objects.filter(
            store=store,
            is_active=True,
            supplier__isnull=False
        ).aggregate(
            total_procured=Sum(F('cost_price') * F('quantity')),
            batches_count=Count('id')
        )

        context['total_suppliers_count'] = all_store_suppliers.count()
        context['total_procurement_spent'] = total_spent_agg['total_procured'] or Decimal('0.00')
        context['total_batches_supplied'] = total_spent_agg['batches_count'] or 0
        return context


class SupplierDetailView(TenantAccessMixin, RoleRequiredMixin, DetailView):
    """
    Detailed supplier dossier showing contact info, license numbers,
    and complete ledger of procured batches and spending.
    """
    model = Supplier
    template_name = 'inventory/supplier_detail.html'
    context_object_name = 'supplier'
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_queryset(self):
        return Supplier.objects.filter(store=self.request.user.store)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batches_qs = self.object.batches.filter(is_active=True).select_related(
            'medicine', 'medicine__unit', 'medicine__category'
        ).order_by('-purchase_date', '-created_at')

        summary_agg = batches_qs.aggregate(
            total_spent=Sum(F('cost_price') * F('quantity')),
            total_units=Sum('quantity'),
            batch_count=Count('id')
        )

        context['batches'] = batches_qs
        context['total_spent'] = summary_agg['total_spent'] or Decimal('0.00')
        context['total_units'] = summary_agg['total_units'] or 0
        context['batch_count'] = summary_agg['batch_count'] or 0
        return context


class SupplierCreateView(TenantAccessMixin, RoleRequiredMixin, CreateView):
    """Store Admin creates a new medicine supplier / distributor."""
    model = Supplier
    form_class = SupplierForm
    template_name = 'inventory/supplier_form.html'
    success_url = reverse_lazy('inventory:supplier_list')
    allowed_roles = [User.Role.STORE_ADMIN]

    def form_valid(self, form):
        form.instance.store = self.request.user.store
        messages.success(self.request, f"Supplier '{form.instance.name}' added successfully.")
        return super().form_valid(form)


class SupplierUpdateView(TenantAccessMixin, RoleRequiredMixin, UpdateView):
    """Store Admin edits supplier information."""
    model = Supplier
    form_class = SupplierForm
    template_name = 'inventory/supplier_form.html'
    success_url = reverse_lazy('inventory:supplier_list')
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_queryset(self):
        return Supplier.objects.filter(store=self.request.user.store)

    def form_valid(self, form):
        messages.success(self.request, f"Supplier '{form.instance.name}' updated successfully.")
        return super().form_valid(form)


class SupplierDeleteView(TenantAccessMixin, RoleRequiredMixin, View):
    """Store Admin removes or deactivates a supplier."""
    allowed_roles = [User.Role.STORE_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        supplier = get_object_or_404(Supplier, pk=pk, store=request.user.store)
        name = supplier.name
        batch_count = supplier.batches.filter(is_active=True).count()
        if batch_count > 0:
            supplier.is_active = False
            supplier.save(update_fields=['is_active'])
            messages.success(request, f"Supplier '{name}' was deactivated (archived) as {batch_count} medicine batch(es) are associated with it.")
        else:
            supplier.delete()
            messages.success(request, f"Supplier '{name}' removed successfully.")
        return redirect('inventory:supplier_list')


# Master Medicine Catalog (Option A)
class MasterCatalogListView(RoleRequiredMixin, ListView):
    model = MasterMedicine
    template_name = 'inventory/master_catalog.html'
    context_object_name = 'master_medicines'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.SUPER_ADMIN, User.Role.STAFF]
    paginate_by = 24

    def get_queryset(self):
        qs = MasterMedicine.objects.filter(is_approved=True)
        q = self.request.GET.get('q', '').strip()
        cat = self.request.GET.get('category', '').strip()
        mfg = self.request.GET.get('mfg', '').strip()
        store_status = self.request.GET.get('store_status', '').strip()
        sort = self.request.GET.get('sort', 'name_asc').strip()

        self.is_fuzzy_search = False
        self.suggested_medicine = ''

        if q:
            q_clean = q.strip('. -_')
            exact_filter = (
                Q(name__icontains=q) |
                Q(salt_composition__icontains=q) |
                Q(manufacturer_name__icontains=q)
            )
            if q_clean and q_clean != q:
                exact_filter |= (
                    Q(name__icontains=q_clean) |
                    Q(salt_composition__icontains=q_clean) |
                    Q(manufacturer_name__icontains=q_clean)
                )

            exact_qs = qs.filter(exact_filter)
            if exact_qs.exists():
                qs = exact_qs
            else:
                try:
                    search_term = q_clean if q_clean else q
                    fuzzy_qs = qs.annotate(
                        sim_name_word=TrigramWordSimilarity(search_term, 'name'),
                        sim_name_full=TrigramSimilarity('name', search_term),
                        sim_salt=TrigramWordSimilarity(search_term, 'salt_composition'),
                    ).annotate(
                        sim_score=Greatest(F('sim_name_word'), F('sim_name_full'), F('sim_salt'))
                    ).filter(
                        sim_score__gte=0.25
                    ).order_by('-sim_score')

                    if fuzzy_qs.exists():
                        self.is_fuzzy_search = True
                        self.suggested_medicine = fuzzy_qs.first().name
                        qs = fuzzy_qs
                    else:
                        qs = exact_qs
                except Exception:
                    qs = exact_qs
        if cat:
            qs = qs.filter(category_name__iexact=cat)
        if mfg:
            qs = qs.filter(manufacturer_name__icontains=mfg)

        if store_status and self.request.user.is_authenticated and hasattr(self.request.user, 'store') and self.request.user.store:
            store_med_names = Medicine.objects.filter(store=self.request.user.store).values_list('name', flat=True)
            if store_status == 'in_store':
                qs = qs.filter(name__in=store_med_names)
            elif store_status == 'not_in_store':
                qs = qs.exclude(name__in=store_med_names)

        if self.is_fuzzy_search and sort == 'name_asc':
            pass  # Retain similarity ranking for typo matches
        elif sort == 'price_low':
            qs = qs.order_by('price')
        elif sort == 'price_high':
            qs = qs.order_by('-price')
        elif sort == 'name_desc':
            qs = qs.order_by('-name')
        else:
            qs = qs.order_by('name')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.core.cache import cache

        page_medicines = context.get('master_medicines') or []
        page_med_names = [m.name for m in page_medicines]
        if self.request.user.is_authenticated and hasattr(self.request.user, 'store') and self.request.user.store and page_med_names:
            context['existing_medicine_names'] = set(
                Medicine.objects.filter(store=self.request.user.store, name__in=page_med_names).values_list('name', flat=True)
            )
        else:
            context['existing_medicine_names'] = set()

        q = self.request.GET.get('q', '').strip()
        cat = self.request.GET.get('category', '').strip()
        mfg = self.request.GET.get('mfg', '').strip()
        store_status = self.request.GET.get('store_status', '').strip()

        if not (q or cat or mfg or store_status) and 'paginator' in context:
            total_master = context['paginator'].count
        else:
            total_master = cache.get_or_set(
                'master_catalog_total_approved',
                lambda: MasterMedicine.objects.filter(is_approved=True).count(),
                300
            )
        context['total_master_count'] = total_master

        context['pending_contributions_count'] = cache.get_or_set(
            'master_catalog_pending_count',
            lambda: MasterMedicine.objects.filter(submission_status='pending').count(),
            300
        )
        context['can_manage_stock'] = (
            self.request.user.is_authenticated and self.request.user.role in [User.Role.STORE_ADMIN, User.Role.STAFF]
        )
        context['is_super_admin'] = (
            self.request.user.is_authenticated and (self.request.user.role == User.Role.SUPER_ADMIN or self.request.user.is_superuser)
        )
        context['is_fuzzy_search'] = getattr(self, 'is_fuzzy_search', False)
        context['suggested_medicine'] = getattr(self, 'suggested_medicine', '')
        return context


class MasterMedicineSearchApiView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.SUPER_ADMIN, User.Role.STAFF]

    def get(self, request, *args, **kwargs):
        q = request.GET.get('q', '').strip()
        if not q or len(q) < 2:
            return JsonResponse({'results': []})

        q_clean = q.strip('. -_')
        exact_filter = Q(name__icontains=q) | Q(salt_composition__icontains=q)
        if q_clean and q_clean != q:
            exact_filter |= Q(name__icontains=q_clean) | Q(salt_composition__icontains=q_clean)

        medicines = MasterMedicine.objects.filter(
            is_approved=True
        ).filter(exact_filter)[:15]

        if not medicines.exists():
            try:
                search_term = q_clean if q_clean else q
                medicines = MasterMedicine.objects.filter(is_approved=True).annotate(
                    sim_name_word=TrigramWordSimilarity(search_term, 'name'),
                    sim_name_full=TrigramSimilarity('name', search_term),
                    sim_salt=TrigramWordSimilarity(search_term, 'salt_composition'),
                ).annotate(
                    sim_score=Greatest(F('sim_name_word'), F('sim_name_full'), F('sim_salt'))
                ).filter(
                    sim_score__gte=0.25
                ).order_by('-sim_score')[:15]
            except Exception:
                medicines = []

        data = []
        for m in medicines:
            data.append({
                'id': m.id,
                'name': m.name,
                'price': str(m.price),
                'manufacturer': m.manufacturer_name,
                'category': m.category_name,
                'pack_size': m.pack_size_label,
                'salt_composition': m.salt_composition,
                'description': m.medicine_desc,
            })
        return JsonResponse({'results': data})


class ImportMasterMedicineView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def post(self, request, pk, *args, **kwargs):
        master = get_object_or_404(MasterMedicine, pk=pk)
        store = request.user.store

        if not store:
            messages.error(request, "You are not assigned to an active store branch.")
            return redirect('inventory:master_catalog')

        # Auto-match or create Category
        cat_name = master.category_name.capitalize() if master.category_name else "Allopathy"
        category, _ = Category.objects.get_or_create(store=store, name=cat_name)

        # Auto-match or create Unit
        unit_label = master.pack_size_label or "Strip"
        unit_short = unit_label[:15]
        unit, _ = Unit.objects.get_or_create(
            store=store,
            name=unit_label,
            defaults={'short_name': unit_short}
        )

        # Auto-match or create Manufacturer
        mfg_name = master.manufacturer_name or "Standard Pharmaceutical"
        manufacturer, _ = Manufacturer.objects.get_or_create(store=store, name=mfg_name)

        # Create or retrieve Medicine
        medicine, created = Medicine.objects.get_or_create(
            store=store,
            name=master.name,
            defaults={
                'generic_name': master.salt_composition or '',
                'category': category,
                'manufacturer': manufacturer,
                'unit': unit,
                'description': master.medicine_desc or '',
            }
        )

        if created:
            messages.success(
                request,
                f"'{master.name}' has been added to your store! Please add your batch & stock quantity."
            )
        else:
            messages.info(
                request,
                f"'{master.name}' is already in your store inventory. Add a new batch or update stock below."
            )

        return redirect(
            f"{reverse('inventory:batch_create', kwargs={'medicine_pk': medicine.pk})}?mrp={master.price}&selling_price={master.price}"
        )


# Super Admin Master Catalog Contribution Moderation (Option 3)
class MasterContributionsListView(RoleRequiredMixin, ListView):
    model = MasterMedicine
    template_name = 'inventory/master_contributions.html'
    context_object_name = 'contributions'
    allowed_roles = [User.Role.SUPER_ADMIN]
    paginate_by = 20

    def get_queryset(self):
        status = self.request.GET.get('status', 'pending').strip()
        qs = MasterMedicine.objects.select_related('submitted_by_store')
        if status in ['pending', 'approved', 'rejected']:
            qs = qs.filter(submission_status=status)
        elif status == 'all':
            qs = qs.exclude(submitted_by_store__isnull=True)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = MasterMedicine.objects.aggregate(
            pending=Count('id', filter=Q(submission_status='pending')),
            approved=Count('id', filter=Q(submission_status='approved', submitted_by_store__isnull=False)),
            rejected=Count('id', filter=Q(submission_status='rejected')),
        )
        context['pending_count'] = counts['pending'] or 0
        context['approved_count'] = counts['approved'] or 0
        context['rejected_count'] = counts['rejected'] or 0
        context['current_status'] = self.request.GET.get('status', 'pending')
        return context


class ApproveMasterContributionView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        obj = get_object_or_404(MasterMedicine, pk=pk)
        obj.is_approved = True
        obj.submission_status = 'approved'
        obj.save()
        messages.success(
            request,
            f"'{obj.name}' approved! It is now published to the National Master Catalog and available to all pharmacy stores."
        )
        return redirect('inventory:master_contributions')


class RejectMasterContributionView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        obj = get_object_or_404(MasterMedicine, pk=pk)
        obj.is_approved = False
        obj.submission_status = 'rejected'
        obj.save()
        messages.warning(request, f"Contribution for '{obj.name}' was rejected.")
        return redirect('inventory:master_contributions')


# Super Admin Master Catalog Management (Create, Edit, Delete)
class MasterMedicineCreateView(RoleRequiredMixin, CreateView):
    model = MasterMedicine
    form_class = MasterMedicineForm
    template_name = 'inventory/master_medicine_form.html'
    allowed_roles = [User.Role.SUPER_ADMIN]
    success_url = reverse_lazy('inventory:master_catalog')

    def form_valid(self, form):
        form.instance.is_approved = True
        form.instance.submission_status = 'approved'
        messages.success(self.request, f"Master medicine '{form.instance.name}' created and published to National Catalog.")
        return super().form_valid(form)


class MasterMedicineUpdateView(RoleRequiredMixin, UpdateView):
    model = MasterMedicine
    form_class = MasterMedicineForm
    template_name = 'inventory/master_medicine_form.html'
    allowed_roles = [User.Role.SUPER_ADMIN]
    success_url = reverse_lazy('inventory:master_catalog')

    def form_valid(self, form):
        messages.success(self.request, f"Master medicine '{form.instance.name}' updated successfully.")
        return super().form_valid(form)


class MasterMedicineDeleteView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        obj = get_object_or_404(MasterMedicine, pk=pk)
        name = obj.name
        obj.delete()
        messages.success(request, f"Medicine '{name}' has been deleted from the National Master Catalog.")
        return redirect('inventory:master_catalog')


class MasterCatalogExportView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def get(self, request, *args, **kwargs):
        qs = MasterMedicine.objects.filter(is_approved=True)
        q = request.GET.get('q', '').strip()
        cat = request.GET.get('category', '').strip()
        mfg = request.GET.get('mfg', '').strip()

        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(salt_composition__icontains=q) |
                Q(manufacturer_name__icontains=q)
            )
        if cat:
            qs = qs.filter(category_name__iexact=cat)
        if mfg:
            qs = qs.filter(manufacturer_name__icontains=mfg)

        sort = request.GET.get('sort', 'name_asc').strip()
        if sort == 'price_low':
            qs = qs.order_by('price')
        elif sort == 'price_high':
            qs = qs.order_by('-price')
        elif sort == 'name_desc':
            qs = qs.order_by('-name')
        else:
            qs = qs.order_by('name')

        def csv_stream():
            yield '\ufeff'  # UTF-8 BOM for Microsoft Excel compatibility
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                'name',
                'price',
                'manufacturer_name',
                'category_name',
                'pack_size_label',
                'salt_composition',
                'medicine_desc',
                'side_effects',
                'drug_interactions',
                'is_discontinued',
            ])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

            for med in qs.iterator(chunk_size=1000):
                writer.writerow([
                    med.name,
                    f"{med.price:.2f}" if med.price is not None else "0.00",
                    med.manufacturer_name or '',
                    med.category_name or '',
                    med.pack_size_label or '',
                    med.salt_composition or '',
                    med.medicine_desc or '',
                    med.side_effects or '',
                    med.drug_interactions or '',
                    'Yes' if med.is_discontinued else 'No',
                ])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f"national_catalog_{timestamp}.csv"
        response = StreamingHttpResponse(csv_stream(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class MasterCatalogSampleCsvView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def get(self, request, *args, **kwargs):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'name',
            'price',
            'manufacturer_name',
            'category_name',
            'pack_size_label',
            'salt_composition',
            'medicine_desc',
            'side_effects',
            'drug_interactions',
            'is_discontinued',
        ])
        writer.writerow([
            'Paracetamol 500mg Tablet',
            '18.50',
            'Cipla Ltd',
            'allopathy',
            'strip of 10 tablets',
            'Paracetamol (500mg)',
            'Used for relief of mild to moderate pain and fever.',
            'Nausea, allergic skin rash (rare).',
            'Avoid with high doses of other paracetamol products.',
            'No'
        ])
        writer.writerow([
            'Augmentin 625 Duo Tablet',
            '204.50',
            'GlaxoSmithKline Pharmaceuticals Ltd',
            'allopathy',
            'strip of 10 tablets',
            'Amoxycillin (500mg) + Clavulanic Acid (125mg)',
            'Broad-spectrum penicillin antibiotic used for bacterial infections.',
            'Diarrhea, nausea, vomiting.',
            'Warfarin, Methotrexate.',
            'No'
        ])
        writer.writerow([
            'Himalaya Liv.52 Syrup',
            '160.00',
            'The Himalaya Drug Company',
            'ayurvedic',
            'bottle of 200 ml',
            'Himsra, Kasani, Mandur bhasma, Kakamachi',
            'Herbal supplement for daily liver care and appetite stimulation.',
            'None reported when used as directed.',
            'None known.',
            'No'
        ])
        content = '\ufeff' + buffer.getvalue()
        response = HttpResponse(content, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="national_catalog_sample_template.csv"'
        return response


class MasterCatalogImportCsvView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]
    template_name = 'inventory/master_catalog_import.html'

    def get(self, request, *args, **kwargs):
        total_catalog = MasterMedicine.objects.filter(is_approved=True).count()
        return render(request, self.template_name, {
            'total_catalog': total_catalog,
        })

    def post(self, request, *args, **kwargs):
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, "Please select a valid CSV file to upload.")
            return redirect('inventory:master_catalog_import_csv')

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, "Invalid file format. Please upload a .csv file.")
            return redirect('inventory:master_catalog_import_csv')

        try:
            raw_bytes = csv_file.read()
            try:
                content = raw_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                content = raw_bytes.decode('latin-1')
        except Exception as e:
            messages.error(request, f"Error reading file: {str(e)}")
            return redirect('inventory:master_catalog_import_csv')

        stream = io.StringIO(content)
        reader = csv.DictReader(stream)

        if not reader.fieldnames:
            messages.error(request, "The CSV file is empty or missing header columns.")
            return redirect('inventory:master_catalog_import_csv')

        def find_value(row_dict, candidate_keys):
            for cand in candidate_keys:
                for k, v in row_dict.items():
                    if k and k.strip().lower() == cand.lower():
                        return (v or '').strip()
            return ''

        duplicate_mode = request.POST.get('duplicate_mode', 'update').strip().lower()

        created_count = 0
        updated_count = 0
        skipped_count = 0
        empty_name_count = 0

        rows_data = []
        for row in reader:
            name = find_value(row, ['name', 'brand_name', 'medicine_name', 'medicine', 'product_name'])
            if not name:
                empty_name_count += 1
                continue

            price_raw = find_value(row, ['price', 'mrp', 'rate', 'cost'])
            try:
                clean_price = price_raw.replace('$', '').replace('₹', '').replace(',', '').strip()
                price_val = Decimal(clean_price) if clean_price else Decimal('0.00')
            except (InvalidOperation, ValueError):
                price_val = Decimal('0.00')

            mfg = find_value(row, ['manufacturer_name', 'manufacturer', 'mfg', 'company'])
            cat = find_value(row, ['category_name', 'category', 'type'])
            pack = find_value(row, ['pack_size_label', 'pack_size', 'pack', 'packaging', 'unit'])
            salt = find_value(row, ['salt_composition', 'composition', 'salts', 'salt', 'generic_name', 'generic'])
            desc = find_value(row, ['medicine_desc', 'description', 'desc'])
            side_effects = find_value(row, ['side_effects', 'side_effect'])
            interactions = find_value(row, ['drug_interactions', 'interactions'])
            discontinued_raw = find_value(row, ['is_discontinued', 'discontinued'])
            is_disc = discontinued_raw.lower() in ['yes', 'true', '1', 'y', 'discontinued']

            defaults = {
                'price': price_val,
                'manufacturer_name': mfg,
                'category_name': cat,
                'pack_size_label': pack,
                'salt_composition': salt,
                'medicine_desc': desc,
                'side_effects': side_effects,
                'drug_interactions': interactions,
                'is_discontinued': is_disc,
                'is_approved': True,
                'submission_status': 'approved',
            }
            rows_data.append((name, defaults))

        BATCH_SIZE = 500
        try:
            for i in range(0, len(rows_data), BATCH_SIZE):
                chunk = rows_data[i:i + BATCH_SIZE]
                chunk_names = [name for name, _ in chunk]

                with transaction.atomic():
                    existing_qs = MasterMedicine.objects.filter(name__in=chunk_names)
                    existing_map = {m.name: m for m in existing_qs}

                    to_create = []
                    to_update = []
                    seen_in_chunk = set()

                    for name, defaults in chunk:
                        if name in seen_in_chunk:
                            continue
                        seen_in_chunk.add(name)

                        if name in existing_map:
                            if duplicate_mode == 'update':
                                obj = existing_map[name]
                                for field, val in defaults.items():
                                    setattr(obj, field, val)
                                to_update.append(obj)
                                updated_count += 1
                            else:
                                skipped_count += 1
                        else:
                            to_create.append(MasterMedicine(name=name, **defaults))
                            created_count += 1

                    if to_create:
                        MasterMedicine.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
                    if to_update:
                        update_fields = [
                            'price', 'manufacturer_name', 'category_name', 'pack_size_label',
                            'salt_composition', 'medicine_desc', 'side_effects',
                            'drug_interactions', 'is_discontinued', 'is_approved', 'submission_status'
                        ]
                        MasterMedicine.objects.bulk_update(to_update, fields=update_fields, batch_size=BATCH_SIZE)

            feedback = [f"Import complete: {created_count} new medicine(s) added"]
            if updated_count:
                feedback.append(f"{updated_count} existing record(s) updated")
            if skipped_count:
                feedback.append(f"{skipped_count} existing record(s) skipped")
            if empty_name_count:
                feedback.append(f"{empty_name_count} row(s) ignored (missing name)")

            messages.success(request, ", ".join(feedback) + ".")
            return redirect('inventory:master_catalog')

        except Exception as e:
            messages.error(request, f"Import failed: {str(e)}")
            return redirect('inventory:master_catalog_import_csv')


# ==============================================================================
# NEAR-EXPIRY WATCHLIST & QUARANTINE CONTROLS
# ==============================================================================

class ExpiryWatchListView(TenantAccessMixin, RoleRequiredMixin, ListView):
    """
    Dedicated Watchlist and Quarantine hub for medicines nearing expiration or quarantined.
    Enables store owners and staff to identify loss risk, isolate batches from POS,
    and manage disposal/supplier returns.
    """
    model = Batch
    template_name = 'inventory/expiry_watch.html'
    context_object_name = 'batches'
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]
    paginate_by = 25

    def get_queryset(self):
        store = self.request.user.store
        today = timezone.localdate()
        d30 = today + timezone.timedelta(days=30)
        d60 = today + timezone.timedelta(days=60)
        d90 = today + timezone.timedelta(days=90)

        qs = Batch.objects.filter(
            store=store,
            is_active=True
        ).select_related('medicine', 'medicine__unit', 'medicine__category', 'quarantined_by')

        # Filter parameters
        timeframe = self.request.GET.get('timeframe', 'all_risk').strip()
        q = self.request.GET.get('q', '').strip()
        cat_id = self.request.GET.get('category', '').strip()
        status_filter = self.request.GET.get('status', '').strip()

        # Apply timeframe filter
        if timeframe == 'expired':
            qs = qs.filter(expiry_date__lte=today, quantity__gt=0).exclude(status=Batch.Status.DISPOSED)
        elif timeframe == '30':
            qs = qs.filter(expiry_date__gt=today, expiry_date__lte=d30, quantity__gt=0, status=Batch.Status.ACTIVE)
        elif timeframe == '60':
            qs = qs.filter(expiry_date__gt=d30, expiry_date__lte=d60, quantity__gt=0, status=Batch.Status.ACTIVE)
        elif timeframe == '90':
            qs = qs.filter(expiry_date__gt=d60, expiry_date__lte=d90, quantity__gt=0, status=Batch.Status.ACTIVE)
        elif timeframe == 'quarantined':
            qs = qs.filter(status=Batch.Status.QUARANTINED)
        elif timeframe == 'disposed':
            qs = qs.filter(status=Batch.Status.DISPOSED)
        elif timeframe == 'returned':
            qs = qs.filter(status=Batch.Status.RETURNED)
        elif timeframe == 'all':
            # all active batches
            pass
        else:
            # default: 'all_risk' -> Expired, expiring within 90 days, or already quarantined
            qs = qs.filter(
                (Q(expiry_date__lte=d90) & Q(quantity__gt=0) & Q(status__in=[Batch.Status.ACTIVE, Batch.Status.QUARANTINED])) |
                Q(status=Batch.Status.QUARANTINED)
            )

        if status_filter:
            qs = qs.filter(status=status_filter)

        if q:
            qs = qs.filter(
                Q(medicine__name__icontains=q) |
                Q(medicine__generic_name__icontains=q) |
                Q(medicine__sku__icontains=q) |
                Q(batch_number__icontains=q)
            )

        if cat_id:
            qs = qs.filter(medicine__category_id=cat_id)

        # Sort order
        sort_by = self.request.GET.get('sort', 'expiry_asc').strip()
        if sort_by == 'expiry_desc':
            qs = qs.order_by('-expiry_date', 'batch_number')
        elif sort_by == 'qty_desc':
            qs = qs.order_by('-quantity', 'expiry_date')
        elif sort_by == 'name':
            qs = qs.order_by('medicine__name', 'expiry_date')
        else:
            # default: earliest expiry first
            qs = qs.order_by('expiry_date', 'batch_number')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store
        today = timezone.localdate()
        d30 = today + timezone.timedelta(days=30)
        d60 = today + timezone.timedelta(days=60)
        d90 = today + timezone.timedelta(days=90)

        all_store_batches = Batch.objects.filter(store=store, is_active=True)

        # Consolidated single aggregate query for all expiry risk buckets
        risk_metrics = all_store_batches.aggregate(
            expired_count=Count('id', filter=Q(expiry_date__lte=today, quantity__gt=0) & ~Q(status__in=[Batch.Status.DISPOSED, Batch.Status.RETURNED])),
            expired_loss=Sum(F('quantity') * F('cost_price'), filter=Q(expiry_date__lte=today, quantity__gt=0) & ~Q(status__in=[Batch.Status.DISPOSED, Batch.Status.RETURNED])),
            days_30_count=Count('id', filter=Q(expiry_date__gt=today, expiry_date__lte=d30, quantity__gt=0, status=Batch.Status.ACTIVE)),
            days_30_qty=Sum('quantity', filter=Q(expiry_date__gt=today, expiry_date__lte=d30, quantity__gt=0, status=Batch.Status.ACTIVE)),
            days_90_count=Count('id', filter=Q(expiry_date__gt=d30, expiry_date__lte=d90, quantity__gt=0, status=Batch.Status.ACTIVE)),
            days_90_qty=Sum('quantity', filter=Q(expiry_date__gt=d30, expiry_date__lte=d90, quantity__gt=0, status=Batch.Status.ACTIVE)),
            quarantined_count=Count('id', filter=Q(status=Batch.Status.QUARANTINED)),
            quarantined_qty=Sum('quantity', filter=Q(status=Batch.Status.QUARANTINED)),
        )

        expired_count = risk_metrics['expired_count'] or 0
        expired_loss_value = risk_metrics['expired_loss'] or Decimal('0.00')
        days_30_count = risk_metrics['days_30_count'] or 0
        days_30_qty = risk_metrics['days_30_qty'] or 0
        days_90_count = risk_metrics['days_90_count'] or 0
        days_90_qty = risk_metrics['days_90_qty'] or 0
        quarantined_count = risk_metrics['quarantined_count'] or 0
        quarantined_qty = risk_metrics['quarantined_qty'] or 0

        # Total at-risk count
        all_risk_count = expired_count + days_30_count + days_90_count + quarantined_count

        context.update({
            'today': today,
            'expired_count': expired_count,
            'expired_loss_value': expired_loss_value,
            'days_30_count': days_30_count,
            'days_30_qty': days_30_qty,
            'days_90_count': days_90_count,
            'days_90_qty': days_90_qty,
            'quarantined_count': quarantined_count,
            'quarantined_qty': quarantined_qty,
            'all_risk_count': all_risk_count,
            'categories': Category.objects.filter(store=store),
            'current_timeframe': self.request.GET.get('timeframe', 'all_risk'),
            'current_q': self.request.GET.get('q', ''),
            'current_category': self.request.GET.get('category', ''),
            'current_sort': self.request.GET.get('sort', 'expiry_asc'),
            'status_choices': Batch.Status.choices,
        })
        return context


class BatchQuarantineActionView(TenantAccessMixin, RoleRequiredMixin, View):
    """
    POST action endpoint to quarantine, release, dispose, or return batches.
    """
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def post(self, request, pk, *args, **kwargs):
        store = request.user.store
        batch = get_object_or_404(Batch, pk=pk, store=store, is_active=True)
        action = request.POST.get('action', '').strip().lower()
        reason = request.POST.get('reason', '').strip()
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('inventory:expiry_watch')

        if action == 'quarantine':
            batch.quarantine(user=request.user, reason=reason or "Quarantined from Expiry Watchlist")
            messages.warning(
                request,
                f"Batch {batch.batch_number} for '{batch.medicine.name}' has been Quarantined. "
                "It is now blocked from POS sales."
            )
        elif action == 'release':
            if batch.is_expired:
                messages.error(
                    request,
                    f"Cannot release Batch {batch.batch_number}: The batch expired on {batch.expiry_date}."
                )
            else:
                batch.release_quarantine()
                messages.success(
                    request,
                    f"Batch {batch.batch_number} for '{batch.medicine.name}' has been released to active stock."
                )
        elif action == 'dispose':
            batch.mark_disposed(user=request.user, reason=reason or "Disposed / Written Off")
            messages.info(
                request,
                f"Batch {batch.batch_number} for '{batch.medicine.name}' marked as Disposed / Written Off."
            )
        elif action == 'return':
            batch.return_to_supplier(user=request.user, reason=reason or "Returned to Supplier")
            messages.info(
                request,
                f"Batch {batch.batch_number} for '{batch.medicine.name}' marked as Returned to Supplier."
            )
        else:
            messages.error(request, "Invalid quarantine action requested.")

        return redirect(next_url)


class ExpiryWatchExportView(TenantAccessMixin, RoleRequiredMixin, View):
    """
    Export filtered near-expiry and quarantined batch inventory to CSV.
    """
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.STAFF]

    def get(self, request, *args, **kwargs):
        store = request.user.store
        today = timezone.localdate()
        d30 = today + timezone.timedelta(days=30)
        d60 = today + timezone.timedelta(days=60)
        d90 = today + timezone.timedelta(days=90)

        qs = Batch.objects.filter(
            store=store,
            is_active=True
        ).select_related('medicine', 'medicine__unit', 'medicine__category')

        timeframe = request.GET.get('timeframe', 'all_risk').strip()
        q = request.GET.get('q', '').strip()
        cat_id = request.GET.get('category', '').strip()

        if timeframe == 'expired':
            qs = qs.filter(expiry_date__lte=today, quantity__gt=0).exclude(status=Batch.Status.DISPOSED)
        elif timeframe == '30':
            qs = qs.filter(expiry_date__gt=today, expiry_date__lte=d30, quantity__gt=0, status=Batch.Status.ACTIVE)
        elif timeframe == '60':
            qs = qs.filter(expiry_date__gt=d30, expiry_date__lte=d60, quantity__gt=0, status=Batch.Status.ACTIVE)
        elif timeframe == '90':
            qs = qs.filter(expiry_date__gt=d60, expiry_date__lte=d90, quantity__gt=0, status=Batch.Status.ACTIVE)
        elif timeframe == 'quarantined':
            qs = qs.filter(status=Batch.Status.QUARANTINED)
        elif timeframe == 'disposed':
            qs = qs.filter(status=Batch.Status.DISPOSED)
        elif timeframe == 'returned':
            qs = qs.filter(status=Batch.Status.RETURNED)
        elif timeframe == 'all':
            pass
        else:
            qs = qs.filter(
                (Q(expiry_date__lte=d90) & Q(quantity__gt=0) & Q(status__in=[Batch.Status.ACTIVE, Batch.Status.QUARANTINED])) |
                Q(status=Batch.Status.QUARANTINED)
            )

        if q:
            qs = qs.filter(
                Q(medicine__name__icontains=q) |
                Q(medicine__generic_name__icontains=q) |
                Q(batch_number__icontains=q)
            )
        if cat_id:
            qs = qs.filter(medicine__category_id=cat_id)

        qs = qs.order_by('expiry_date', 'medicine__name')

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        filename = f"expiry_watchlist_{store.code}_{today.strftime('%Y%m%d')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Medicine Name',
            'Generic Composition',
            'Category',
            'Batch Number',
            'Expiry Date',
            'Days Remaining',
            'Available Stock',
            'Unit',
            'Cost Price (Rs)',
            'MRP (Rs)',
            'Total Cost Value (Rs)',
            'Total MRP Value (Rs)',
            'Status',
            'Quarantine/Action Reason',
        ])

        for b in qs:
            days_left = (b.expiry_date - today).days
            cost_val = (b.quantity * b.cost_price).quantize(Decimal('0.01'))
            mrp_val = (b.quantity * b.mrp).quantize(Decimal('0.01'))
            days_str = f"Expired ({abs(days_left)}d ago)" if days_left < 0 else (f"Today" if days_left == 0 else f"{days_left} days")

            writer.writerow([
                b.medicine.name,
                b.medicine.generic_name or '',
                b.medicine.category.name if b.medicine.category else '',
                b.batch_number,
                b.expiry_date.strftime('%Y-%m-%d'),
                days_str,
                b.quantity,
                b.medicine.unit.short_name if b.medicine.unit else '',
                str(b.cost_price),
                str(b.mrp),
                str(cost_val),
                str(mrp_val),
                b.get_status_display(),
                b.quarantine_reason or '',
            ])

        return response





