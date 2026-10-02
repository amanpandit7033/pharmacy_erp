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

        # SMTP Outgoing Mail Settings
        settings_obj.smtp_is_enabled = request.POST.get('smtp_is_enabled') in ['1', 'on', 'true', 'True']
        settings_obj.send_welcome_email = request.POST.get('send_welcome_email') in ['1', 'on', 'true', 'True']
        settings_obj.smtp_host = request.POST.get('smtp_host', '').strip()
        port_raw = request.POST.get('smtp_port', '').strip()
        settings_obj.smtp_port = int(port_raw) if port_raw.isdigit() else 587
        settings_obj.smtp_user = request.POST.get('smtp_user', '').strip()
        
        # Only update password if a new one was provided, otherwise preserve existing
        new_smtp_password = request.POST.get('smtp_password', '')
        if new_smtp_password:
            settings_obj.smtp_password = new_smtp_password.strip()

        settings_obj.smtp_use_tls = request.POST.get('smtp_use_tls') in ['1', 'on', 'true', 'True']
        settings_obj.smtp_use_ssl = request.POST.get('smtp_use_ssl') in ['1', 'on', 'true', 'True']
        settings_obj.smtp_default_from_email = request.POST.get('smtp_default_from_email', '').strip()

        settings_obj.save()
        messages.success(request, f"Platform settings and SMTP configuration updated successfully.")
        return redirect('core:platform_settings')


class TestSmtpConnectionView(RoleRequiredMixin, View):
    """
    AJAX endpoint for testing the configured SMTP credentials live.
    Accessible exclusively by Super Admin.
    """
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, *args, **kwargs):
        from core.emails import test_smtp_connection
        recipient_email = request.POST.get('test_email', '').strip()
        if not recipient_email:
            return JsonResponse({'success': False, 'message': 'Please enter a recipient email address to test.'})

        settings_obj = PlatformSetting.get_settings()

        # If test request includes temporarily edited form values, test with those values
        temp_host = request.POST.get('smtp_host', '').strip()
        if temp_host:
            settings_obj.smtp_host = temp_host
            port_raw = request.POST.get('smtp_port', '').strip()
            settings_obj.smtp_port = int(port_raw) if port_raw.isdigit() else 587
            settings_obj.smtp_user = request.POST.get('smtp_user', '').strip()
            temp_pass = request.POST.get('smtp_password', '').strip()
            if temp_pass:
                settings_obj.smtp_password = temp_pass
            settings_obj.smtp_use_tls = request.POST.get('smtp_use_tls') in ['1', 'on', 'true', 'True']
            settings_obj.smtp_use_ssl = request.POST.get('smtp_use_ssl') in ['1', 'on', 'true', 'True']
            settings_obj.smtp_default_from_email = request.POST.get('smtp_default_from_email', '').strip()
            settings_obj.smtp_is_enabled = True

        success, msg = test_smtp_connection(recipient_email, platform_setting=settings_obj)
        return JsonResponse({'success': success, 'message': msg})


class PWAManifestView(View):
    """
    Dynamically generates the PWA manifest.json.
    Configures start_url with client=pwa to trigger session isolation.
    """
    def get(self, request, *args, **kwargs):
        settings_obj = PlatformSetting.get_settings()
        brand_name = settings_obj.brand_name or "Azmed Pharmacy ERP"
        
        icons = []
        if settings_obj.logo_icon:
            icons.append({
                "src": settings_obj.logo_icon.url,
                "sizes": "192x192 512x512",
                "type": "image/png",
                "purpose": "any maskable"
            })

        manifest = {
            "id": "/?client=pwa",
            "name": brand_name,
            "short_name": brand_name[:12],
            "description": f"{brand_name} Management & POS System",
            "start_url": "/?client=pwa",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f4f7fb",
            "theme_color": "#283891",
            "orientation": "any",
            "icons": icons
        }
        response = JsonResponse(manifest, content_type='application/manifest+json')
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response


class PWAServiceWorkerView(View):
    """
    Serves a clean sw.js for PWA installation without network interception.
    Does not tamper with fetch events, guaranteeing zero CSS, CDN, or logout issues.
    """
    def get(self, request, *args, **kwargs):
        from django.http import HttpResponse
        sw_code = """// Pharmacy ERP Lightweight Service Worker
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});
"""
        response = HttpResponse(sw_code, content_type='application/javascript')
        response['Service-Worker-Allowed'] = '/'
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response


