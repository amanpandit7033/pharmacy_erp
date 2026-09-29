from django.views import View
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Sum, Count, Value
from django.db.models.functions import Coalesce
from accounts.models import User
from stores.models import Store
from inventory.models import Medicine, MasterMedicine, Category, Unit
from billing.models import Invoice
from core.models import PlatformSetting
from core.mixins import RoleRequiredMixin



class SearchSuggestionsView(View):
    """
    Unified auto-suggestion endpoint for ERP search inputs.
    Strictly enforces multi-tenant boundaries and role authorizations.
    """

    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'suggestions': []}, status=401)

        q = request.GET.get('q', '').strip()
        scope = request.GET.get('scope', '').strip().lower()

        if not q or len(q) < 1:
            return JsonResponse({'suggestions': []})

        suggestions = []
        user = request.user
        store = getattr(user, 'store', None)

        if scope == 'medicines':
            if store:
                qs = Medicine.objects.filter(store=store).annotate(
                    annotated_stock=Coalesce(
                        Sum('batches__quantity', filter=Q(batches__is_active=True)),
                        Value(0)
                    )
                ).filter(
                    Q(name__icontains=q) |
                    Q(generic_name__icontains=q) |
                    Q(sku__icontains=q) |
                    Q(rack_location__icontains=q)
                ).order_by('-annotated_stock', 'name')[:8]

                for m in qs:
                    sub_parts = []
                    if m.generic_name:
                        sub_parts.append(m.generic_name)
                    if m.sku:
                        sub_parts.append(f"SKU: {m.sku}")
                    if m.rack_location:
                        sub_parts.append(f"Rack: {m.rack_location}")
                    subtitle = " • ".join(sub_parts) if sub_parts else "Product"
                    suggestions.append({
                        'value': m.name,
                        'title': m.name,
                        'subtitle': subtitle,
                        'badge': f"Stock: {m.annotated_stock}",
                        'category': 'Product'
                    })

        elif scope == 'master_catalog':
            qs = MasterMedicine.objects.filter(
                Q(name__icontains=q) |
                Q(salt_composition__icontains=q) |
                Q(manufacturer_name__icontains=q)
            )[:8]

            for m in qs:
                sub_parts = []
                if m.salt_composition:
                    sub_parts.append(m.salt_composition[:40])
                if m.manufacturer_name:
                    sub_parts.append(m.manufacturer_name)
                subtitle = " • ".join(sub_parts) if sub_parts else "Catalog Medicine"
                suggestions.append({
                    'value': m.name,
                    'title': m.name,
                    'subtitle': subtitle,
                    'badge': m.category_name.capitalize() if m.category_name else "National Catalog",
                    'category': 'Catalog'
                })

        elif scope == 'categories':
            if store:
                qs = Category.objects.filter(store=store).filter(
                    Q(name__icontains=q) | Q(description__icontains=q)
                ).annotate(num_meds=Count('medicines'))[:8]

                for c in qs:
                    suggestions.append({
                        'value': c.name,
                        'title': c.name,
                        'subtitle': c.description or "Category",
                        'badge': f"{c.num_meds} products",
                        'category': 'Category'
                    })

        elif scope == 'units':
            if store:
                qs = Unit.objects.filter(store=store).filter(
                    Q(name__icontains=q) | Q(short_name__icontains=q)
                )[:8]

                for u in qs:
                    suggestions.append({
                        'value': u.name,
                        'title': f"{u.name} ({u.short_name})",
                        'subtitle': f"Unit symbol: {u.short_name}",
                        'badge': "Unit",
                        'category': 'Unit'
                    })

        elif scope == 'stores':
            if user.role == User.Role.SUPER_ADMIN or user.is_superuser:
                qs = Store.objects.filter(
                    Q(name__icontains=q) |
                    Q(code__icontains=q) |
                    Q(city__icontains=q) |
                    Q(phone__icontains=q) |
                    Q(license_number__icontains=q)
                )[:8]

                for s in qs:
                    suggestions.append({
                        'value': s.name,
                        'title': s.name,
                        'subtitle': f"Code: {s.code} • {s.city}, {s.state}",
                        'badge': "Active" if s.is_active else "Inactive",
                        'category': 'Store'
                    })

        elif scope == 'store_admins':
            if user.role == User.Role.SUPER_ADMIN or user.is_superuser:
                qs = User.objects.filter(role=User.Role.STORE_ADMIN).select_related('store').filter(
                    Q(username__icontains=q) |
                    Q(first_name__icontains=q) |
                    Q(last_name__icontains=q) |
                    Q(email__icontains=q) |
                    Q(phone__icontains=q) |
                    Q(store__name__icontains=q)
                )[:8]

                for u in qs:
                    st_name = u.store.name if u.store else "Unassigned"
                    name_disp = u.get_full_name() or u.username
                    suggestions.append({
                        'value': u.username,
                        'title': f"{name_disp} (@{u.username})",
                        'subtitle': f"Store: {st_name} • {u.email}",
                        'badge': "Store Admin",
                        'category': 'Store Admin'
                    })

        elif scope == 'staff':
            if store and (user.role == User.Role.STORE_ADMIN or user.is_superuser):
                qs = User.objects.filter(role=User.Role.STAFF, store=store).filter(
                    Q(username__icontains=q) |
                    Q(first_name__icontains=q) |
                    Q(last_name__icontains=q) |
                    Q(email__icontains=q) |
                    Q(phone__icontains=q)
                )[:8]

                for u in qs:
                    name_disp = u.get_full_name() or u.username
                    suggestions.append({
                        'value': u.username,
                        'title': f"{name_disp} (@{u.username})",
                        'subtitle': u.email or u.phone or "Staff Member",
                        'badge': "Active" if u.is_active else "Inactive",
                        'category': 'Staff'
                    })

        elif scope == 'invoices':
            if store:
                qs = Invoice.objects.filter(store=store).filter(
                    Q(invoice_number__icontains=q) |
                    Q(customer_name__icontains=q) |
                    Q(customer_phone__icontains=q) |
                    Q(doctor_name__icontains=q)
                ).order_by('-created_at')[:8]

                for inv in qs:
                    suggestions.append({
                        'value': inv.invoice_number,
                        'title': f"{inv.invoice_number} - {inv.customer_name}",
                        'subtitle': f"Ph: {inv.customer_phone or 'Walk-in'} • {inv.created_at.strftime('%d %b %Y')}",
                        'badge': f"{inv.store.currency}{inv.total_amount:.2f} ({inv.status})",
                        'category': 'Invoice'
                    })

        return JsonResponse({'suggestions': suggestions})


class PlatformSettingsView(RoleRequiredMixin, View):
    """
    Platform branding and configuration dashboard for Super Admin.
    Allows changing platform brand name, 1:1 square logo icon, and tagline.
    """
    allowed_roles = [User.Role.SUPER_ADMIN]
    template_name = 'core/platform_settings.html'

    def get(self, request, *args, **kwargs):
        settings_obj = PlatformSetting.get_settings()
        return render(request, self.template_name, {
            'settings': settings_obj,
        })

    def post(self, request, *args, **kwargs):
        settings_obj = PlatformSetting.get_settings()
        brand_name = request.POST.get('brand_name', '').strip()
        tagline = request.POST.get('tagline', '').strip()
        footer_text = request.POST.get('footer_text', '').strip()
        footer_contact_info = request.POST.get('footer_contact_info', '').strip()
        show_login_footer = request.POST.get('show_login_footer') in ['1', 'on', 'true', 'True']
        remove_logo = request.POST.get('remove_logo') == '1'

        if not brand_name:
            messages.error(request, "Brand name cannot be empty.")
            return render(request, self.template_name, {'settings': settings_obj})

        settings_obj.brand_name = brand_name
        settings_obj.tagline = tagline
        settings_obj.footer_text = footer_text
        settings_obj.footer_contact_info = footer_contact_info
        settings_obj.show_login_footer = show_login_footer

        if remove_logo:
            if settings_obj.logo_icon:
                settings_obj.logo_icon.delete(save=False)
                settings_obj.logo_icon = None
        elif 'logo_icon' in request.FILES:
            logo_file = request.FILES['logo_icon']
            allowed_types = ['image/png', 'image/jpeg', 'image/jpg', 'image/svg+xml', 'image/webp']
            if hasattr(logo_file, 'content_type') and logo_file.content_type not in allowed_types:
                messages.error(request, "Please upload a valid image file (PNG, JPG, SVG, WebP).")
                return render(request, self.template_name, {'settings': settings_obj})

            if settings_obj.logo_icon:
                settings_obj.logo_icon.delete(save=False)
            settings_obj.logo_icon = logo_file

        settings_obj.save()
        messages.success(request, f"Platform settings updated! Brand name is now '{settings_obj.brand_name}'.")
        return redirect('core:platform_settings')

