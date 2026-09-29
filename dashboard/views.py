from decimal import Decimal
from datetime import timedelta
from django.views.generic import TemplateView
from django.utils import timezone
from django.db.models import Sum, Count, F, Q

from accounts.models import User
from stores.models import Store
from inventory.models import Medicine, Batch
from billing.models import Invoice, InvoiceItem
from core.mixins import RoleRequiredMixin
from dashboard.analytics import (
    parse_date_range, compute_financials, compute_growth_pct,
    classify_store_performance, build_timeline_points
)


class SuperAdminDashboardView(RoleRequiredMixin, TemplateView):
    template_name = 'dashboard/super_admin_dashboard.html'
    allowed_roles = [User.Role.SUPER_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_stores'] = Store.all_objects.count()
        context['active_stores'] = Store.objects.count()
        context['inactive_stores'] = Store.all_objects.filter(is_active=False).count()
        context['total_store_admins'] = User.objects.filter(role=User.Role.STORE_ADMIN).count()
        context['total_staff'] = User.objects.filter(role=User.Role.STAFF).count()
        context['recent_stores'] = Store.all_objects.order_by('-created_at')[:5]
        return context


class StoreAdminDashboardView(RoleRequiredMixin, TemplateView):
    template_name = 'dashboard/store_admin_dashboard.html'
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store
        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)
        month_start = today.replace(day=1)
        prev_month_end = month_start - timezone.timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)

        # 1. Invoices & Sales Metrics
        invoices_today = Invoice.objects.filter(store=store, created_at__date=today, status=Invoice.Status.PAID)
        today_sales = invoices_today.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        today_bills_count = invoices_today.count()

        invoices_yesterday = Invoice.objects.filter(store=store, created_at__date=yesterday, status=Invoice.Status.PAID)
        yesterday_sales = invoices_yesterday.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        if yesterday_sales > 0:
            today_growth_pct = round(float((today_sales - yesterday_sales) / yesterday_sales * 100), 1)
        else:
            today_growth_pct = 100.0 if today_sales > 0 else 0.0

        invoices_month = Invoice.objects.filter(store=store, created_at__date__gte=month_start, status=Invoice.Status.PAID)
        month_sales = invoices_month.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        month_bills_count = invoices_month.count()

        invoices_prev_month = Invoice.objects.filter(
            store=store,
            created_at__date__gte=prev_month_start,
            created_at__date__lte=prev_month_end,
            status=Invoice.Status.PAID
        )
        prev_month_sales = invoices_prev_month.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        if prev_month_sales > 0:
            month_growth_pct = round(float((month_sales - prev_month_sales) / prev_month_sales * 100), 1)
        else:
            month_growth_pct = 100.0 if month_sales > 0 else 0.0

        # 2. Inventory valuation
        active_batches = Batch.objects.filter(store=store, is_active=True, quantity__gt=0)
        cost_val = sum((b.cost_price * b.quantity for b in active_batches), Decimal('0.00'))
        retail_val = sum((b.selling_price * b.quantity for b in active_batches), Decimal('0.00'))
        margin_pct = round(float((retail_val - cost_val) / retail_val * 100), 1) if retail_val > 0 else 0.0

        # 3. Catalog & Team metrics
        medicines = Medicine.objects.filter(store=store, is_active=True)
        total_medicines = medicines.count()
        in_stock_medicines_count = medicines.filter(
            batches__quantity__gt=0,
            batches__is_active=True
        ).distinct().count()
        stock_health_rate = round((in_stock_medicines_count / total_medicines * 100)) if total_medicines > 0 else 100

        low_stock_count = medicines.annotate(
            total_qty=Sum('batches__quantity', filter=Q(batches__is_active=True))
        ).filter(Q(total_qty__lte=F('min_stock_level')) | Q(total_qty__isnull=True)).count()

        expiry_threshold = today + timezone.timedelta(days=60)
        expiring_batches = Batch.objects.filter(
            store=store,
            is_active=True,
            quantity__gt=0,
            expiry_date__lte=expiry_threshold
        ).select_related('medicine').order_by('expiry_date')
        expiring_batches_count = expiring_batches.count()

        store_staff_count = User.objects.filter(store=store, role=User.Role.STAFF, is_active=True).count()

        # 4. Customer and Channel Breakdown
        all_store_invoices = Invoice.objects.filter(store=store)
        total_customers = all_store_invoices.values('customer_name').distinct().count()
        prescription_count = all_store_invoices.exclude(doctor_name='').count()
        walkin_count = all_store_invoices.filter(doctor_name='').count()

        # 5. Top Selling Medicines (from real InvoiceItem data)
        best_selling_medicines = list(
            InvoiceItem.objects.filter(store=store, invoice__status=Invoice.Status.PAID)
            .values('medicine_name')
            .annotate(
                total_sold=Sum('quantity'),
                total_revenue=Sum('total_price'),
                orders_count=Count('id')
            )
            .order_by('-total_revenue')[:5]
        )

        # 6. Recent Invoices
        recent_invoices = all_store_invoices.select_related('created_by').order_by('-created_at')[:6]

        # 7. Last 7 Days Performance & Chart Points
        trend_days = []
        for i in range(6, -1, -1):
            d = today - timezone.timedelta(days=i)
            day_invs = Invoice.objects.filter(store=store, created_at__date=d, status=Invoice.Status.PAID)
            day_total = day_invs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            trend_days.append({
                'date': d,
                'date_str': d.strftime('%d %b'),
                'day_name': d.strftime('%a'),
                'sales': float(day_total),
                'count': day_invs.count()
            })

        max_sales = max([t['sales'] for t in trend_days] + [1.0])
        max_sales_val = max(t['sales'] for t in trend_days)
        active_day_index = 6
        for idx, t in enumerate(trend_days):
            t['height_pct'] = max(12, int((t['sales'] / max_sales) * 85)) if max_sales > 0 else 12
            if max_sales_val > 0 and t['sales'] == max_sales_val:
                active_day_index = idx

        # Generate SVG coordinates
        points = []
        for i, t in enumerate(trend_days):
            x = 20 + i * 110  # 20, 130, 240, 350, 460, 570, 680
            y = 160 - int((t['sales'] / max_sales) * 120) if max_sales > 0 else 150
            points.append({
                'x': x,
                'y': y,
                'sales': t['sales'],
                'date_str': t['date_str'],
                'day_name': t['day_name']
            })

        path_segments = [f"M {points[0]['x']} {points[0]['y']}"]
        for p in points[1:]:
            path_segments.append(f"L {p['x']} {p['y']}")
        chart_line_path = " ".join(path_segments)
        chart_area_path = f"{chart_line_path} L {points[-1]['x']} 180 L {points[0]['x']} 180 Z"

        active_point = points[active_day_index]

        context.update({
            'today_sales': today_sales,
            'today_bills_count': today_bills_count,
            'today_growth_pct': today_growth_pct,
            'yesterday_sales': yesterday_sales,
            'month_sales': month_sales,
            'month_bills_count': month_bills_count,
            'month_growth_pct': month_growth_pct,
            'prev_month_sales': prev_month_sales,
            'stock_cost_value': cost_val,
            'stock_retail_value': retail_val,
            'stock_margin_pct': margin_pct,
            'total_medicines': total_medicines,
            'in_stock_medicines_count': in_stock_medicines_count,
            'stock_health_rate': stock_health_rate,
            'low_stock_count': low_stock_count,
            'expiring_batches_count': expiring_batches_count,
            'expiring_batches': expiring_batches[:5],
            'store_staff_count': store_staff_count,
            'total_customers': total_customers,
            'prescription_count': prescription_count,
            'walkin_count': walkin_count,
            'best_selling_medicines': best_selling_medicines,
            'recent_invoices': recent_invoices,
            'trend_days': trend_days,
            'active_day_index': active_day_index,
            'chart_line_path': chart_line_path,
            'chart_area_path': chart_area_path,
            'active_point': active_point,
            'chart_points': points,
        })
        return context


class StaffDashboardView(RoleRequiredMixin, TemplateView):
    template_name = 'dashboard/staff_dashboard.html'
    allowed_roles = [User.Role.STAFF]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.request.user.store
        user = self.request.user
        today = timezone.localdate()

        my_invoices_today = Invoice.objects.filter(store=store, created_by=user, created_at__date=today, status=Invoice.Status.PAID)
        context['my_today_sales'] = my_invoices_today.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        context['my_today_count'] = my_invoices_today.count()

        context['total_medicines'] = Medicine.objects.filter(store=store, is_active=True).count()
        context['recent_invoices'] = Invoice.objects.filter(store=store, created_by=user).order_by('-created_at')[:5]

        return context


class AnalyticsReportView(RoleRequiredMixin, TemplateView):
    """
    Role-aware analytics report covering:
    - Super Admin: All stores financial overview, P&L, growth/down trends, and ranking.
    - Store Admin: Store P&L statement, COGS, gross margin, inventory losses, top profitable drugs.
    - Staff: Counter billing sales performance, bills count, top dispensed medicines.
    """
    allowed_roles = [User.Role.SUPER_ADMIN, User.Role.STORE_ADMIN, User.Role.STAFF]

    def get_template_names(self):
        role = self.request.user.role
        if role == User.Role.SUPER_ADMIN or self.request.user.is_superuser:
            return ['dashboard/analytics_super_admin.html']
        elif role == User.Role.STORE_ADMIN:
            return ['dashboard/analytics_store_admin.html']
        else:
            return ['dashboard/analytics_staff.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        role = user.role if not user.is_superuser else User.Role.SUPER_ADMIN

        date_info = parse_date_range(self.request)
        context.update(date_info)
        curr_start = date_info['curr_start']
        curr_end = date_info['curr_end']
        prev_start = date_info['prev_start']
        prev_end = date_info['prev_end']

        if role == User.Role.SUPER_ADMIN:
            self._build_super_admin_context(context, curr_start, curr_end, prev_start, prev_end)
        elif role == User.Role.STORE_ADMIN:
            self._build_store_admin_context(context, curr_start, curr_end, prev_start, prev_end)
        else:
            self._build_staff_context(context, curr_start, curr_end, prev_start, prev_end)

        return context

    def _generate_daily_points(self, start_date, end_date, store=None):
        days_data = []
        delta_days = (end_date - start_date).days
        step = 1 if delta_days <= 30 else max(1, delta_days // 20)

        d = start_date
        while d <= end_date:
            day_inv_filter = Q(status=Invoice.Status.PAID, created_at__date=d)
            if store:
                day_inv_filter &= Q(store=store)

            day_invs = Invoice.objects.filter(day_inv_filter)
            day_fin = compute_financials(day_invs, store=store, date_range=(d, d))

            days_data.append({
                'date': d,
                'date_str': d.strftime('%d %b'),
                'day_name': d.strftime('%a'),
                'revenue': float(day_fin['revenue']),
                'profit': float(day_fin['gross_profit']),
                'invoices_count': day_fin['invoices_count'],
            })
            d += timedelta(days=step)

        return days_data

    def _build_super_admin_context(self, context, curr_start, curr_end, prev_start, prev_end):
        selected_store_id = self.request.GET.get('store', '').strip()
        all_stores = Store.all_objects.all().order_by('name')
        context['stores_list'] = all_stores
        context['selected_store_id'] = selected_store_id

        # Invoices scope
        curr_inv_filter = Q(status=Invoice.Status.PAID, created_at__date__gte=curr_start, created_at__date__lte=curr_end)
        prev_inv_filter = Q(status=Invoice.Status.PAID, created_at__date__gte=prev_start, created_at__date__lte=prev_end)

        selected_store = None
        if selected_store_id:
            try:
                selected_store = Store.all_objects.get(pk=selected_store_id)
                curr_inv_filter &= Q(store_id=selected_store_id)
                prev_inv_filter &= Q(store_id=selected_store_id)
            except Store.DoesNotExist:
                selected_store_id = ''
        context['selected_store'] = selected_store

        curr_invoices = Invoice.objects.filter(curr_inv_filter)
        prev_invoices = Invoice.objects.filter(prev_inv_filter)

        curr_fin = compute_financials(curr_invoices, store=selected_store, date_range=(curr_start, curr_end))
        prev_fin = compute_financials(prev_invoices, store=selected_store, date_range=(prev_start, prev_end))

        # Growth metrics
        rev_growth_pct = compute_growth_pct(curr_fin['revenue'], prev_fin['revenue'])
        profit_growth_pct = compute_growth_pct(curr_fin['gross_profit'], prev_fin['gross_profit'])
        net_profit_growth_pct = compute_growth_pct(curr_fin['net_profit'], prev_fin['net_profit'])

        # Store-by-Store Growth & Down Performance Matrix
        stores_analytics = []
        growing_stores = []
        down_stores = []
        at_risk_stores = []
        stable_stores = []

        for st in all_stores:
            st_curr_inv = Invoice.objects.filter(store=st, status=Invoice.Status.PAID, created_at__date__gte=curr_start, created_at__date__lte=curr_end)
            st_prev_inv = Invoice.objects.filter(store=st, status=Invoice.Status.PAID, created_at__date__gte=prev_start, created_at__date__lte=prev_end)

            st_curr_fin = compute_financials(st_curr_inv, store=st, date_range=(curr_start, curr_end))
            st_prev_fin = compute_financials(st_prev_inv, store=st, date_range=(prev_start, prev_end))

            st_rev_growth = compute_growth_pct(st_curr_fin['revenue'], st_prev_fin['revenue'])
            st_profit_growth = compute_growth_pct(st_curr_fin['gross_profit'], st_prev_fin['gross_profit'])

            classification = classify_store_performance(
                st_rev_growth, st_profit_growth,
                st_curr_fin['net_profit'], st_curr_fin['inventory_loss'],
                st_curr_fin['gross_profit']
            )

            store_row = {
                'store': st,
                'revenue': st_curr_fin['revenue'],
                'prev_revenue': st_prev_fin['revenue'],
                'cogs': st_curr_fin['cogs'],
                'gross_profit': st_curr_fin['gross_profit'],
                'gross_margin_pct': st_curr_fin['gross_margin_pct'],
                'inventory_loss': st_curr_fin['inventory_loss'],
                'net_profit': st_curr_fin['net_profit'],
                'invoices_count': st_curr_fin['invoices_count'],
                'aov': st_curr_fin['aov'],
                'rev_growth_pct': st_rev_growth,
                'profit_growth_pct': st_profit_growth,
                'trend': classification,
            }
            stores_analytics.append(store_row)

            if classification['status'] == 'GROWING':
                growing_stores.append(store_row)
            elif classification['status'] == 'DOWN':
                down_stores.append(store_row)
            elif classification['status'] == 'AT_RISK':
                at_risk_stores.append(store_row)
            else:
                stable_stores.append(store_row)

        sort_by = self.request.GET.get('sort', 'rev_desc')
        if sort_by == 'growth_desc':
            stores_analytics.sort(key=lambda x: x['rev_growth_pct'], reverse=True)
        elif sort_by == 'growth_asc':
            stores_analytics.sort(key=lambda x: x['rev_growth_pct'])
        elif sort_by == 'profit_desc':
            stores_analytics.sort(key=lambda x: x['gross_profit'], reverse=True)
        elif sort_by == 'loss_desc':
            stores_analytics.sort(key=lambda x: x['inventory_loss'], reverse=True)
        elif sort_by == 'name':
            stores_analytics.sort(key=lambda x: x['store'].name)
        else:
            stores_analytics.sort(key=lambda x: x['revenue'], reverse=True)

        top_growth_store = max(stores_analytics, key=lambda x: x['rev_growth_pct']) if stores_analytics else None
        top_down_store = min(stores_analytics, key=lambda x: x['rev_growth_pct']) if stores_analytics else None
        top_revenue_store = max(stores_analytics, key=lambda x: x['revenue']) if stores_analytics else None

        days_data = self._generate_daily_points(curr_start, curr_end, store=selected_store)
        chart_data = build_timeline_points(days_data)

        context.update({
            'curr_fin': curr_fin,
            'prev_fin': prev_fin,
            'rev_growth_pct': rev_growth_pct,
            'profit_growth_pct': profit_growth_pct,
            'net_profit_growth_pct': net_profit_growth_pct,
            'stores_analytics': stores_analytics,
            'growing_count': len(growing_stores),
            'down_count': len(down_stores),
            'at_risk_count': len(at_risk_stores),
            'stable_count': len(stable_stores),
            'top_growth_store': top_growth_store,
            'top_down_store': top_down_store,
            'top_revenue_store': top_revenue_store,
            'chart_data': chart_data,
            'days_data': days_data,
            'sort_by': sort_by,
        })

    def _build_store_admin_context(self, context, curr_start, curr_end, prev_start, prev_end):
        store = self.request.user.store
        curr_invoices = Invoice.objects.filter(store=store, status=Invoice.Status.PAID, created_at__date__gte=curr_start, created_at__date__lte=curr_end)
        prev_invoices = Invoice.objects.filter(store=store, status=Invoice.Status.PAID, created_at__date__gte=prev_start, created_at__date__lte=prev_end)

        curr_fin = compute_financials(curr_invoices, store=store, date_range=(curr_start, curr_end))
        prev_fin = compute_financials(prev_invoices, store=store, date_range=(prev_start, prev_end))

        rev_growth_pct = compute_growth_pct(curr_fin['revenue'], prev_fin['revenue'])
        profit_growth_pct = compute_growth_pct(curr_fin['gross_profit'], prev_fin['gross_profit'])
        net_profit_growth_pct = compute_growth_pct(curr_fin['net_profit'], prev_fin['net_profit'])

        # Top 10 Profitable Medicines
        curr_items = InvoiceItem.objects.filter(
            store=store,
            invoice__status=Invoice.Status.PAID,
            invoice__created_at__date__gte=curr_start,
            invoice__created_at__date__lte=curr_end
        )
        profitable_medicines = list(
            curr_items.values('medicine_name')
            .annotate(
                total_qty=Sum('quantity'),
                total_revenue=Sum('total_price'),
                total_cost=Sum(F('quantity') * F('batch__cost_price')),
                orders_count=Count('id')
            )
        )
        for med in profitable_medicines:
            cost = med['total_cost'] or Decimal('0.00')
            rev = med['total_revenue'] or Decimal('0.00')
            med['profit'] = rev - cost
            med['margin_pct'] = round(float((med['profit'] / rev) * 100), 1) if rev > 0 else 0.0
        profitable_medicines.sort(key=lambda x: x['profit'], reverse=True)
        profitable_medicines = profitable_medicines[:10]

        # Payment Methods Breakdown
        payment_methods = list(
            curr_invoices.values('payment_method')
            .annotate(
                total_amount=Sum('total_amount'),
                count=Count('id')
            )
            .order_by('-total_amount')
        )
        for pm in payment_methods:
            pm_total = pm['total_amount'] or Decimal('0.00')
            pm['pct'] = round(float((pm_total / curr_fin['revenue']) * 100), 1) if curr_fin['revenue'] > 0 else 0.0

        # Staff Billing Performance at this Store
        staff_performance = list(
            curr_invoices.values('created_by__username', 'created_by__first_name', 'created_by__last_name')
            .annotate(
                total_sales=Sum('total_amount'),
                bills_count=Count('id')
            )
            .order_by('-total_sales')
        )
        for sp in staff_performance:
            s_sales = sp['total_sales'] or Decimal('0.00')
            s_count = sp['bills_count'] or 0
            sp['aov'] = (s_sales / s_count) if s_count > 0 else Decimal('0.00')

        days_data = self._generate_daily_points(curr_start, curr_end, store=store)
        chart_data = build_timeline_points(days_data)

        context.update({
            'curr_fin': curr_fin,
            'prev_fin': prev_fin,
            'rev_growth_pct': rev_growth_pct,
            'profit_growth_pct': profit_growth_pct,
            'net_profit_growth_pct': net_profit_growth_pct,
            'profitable_medicines': profitable_medicines,
            'payment_methods': payment_methods,
            'staff_performance': staff_performance,
            'chart_data': chart_data,
            'days_data': days_data,
        })

    def _build_staff_context(self, context, curr_start, curr_end, prev_start, prev_end):
        store = self.request.user.store
        user = self.request.user

        curr_invoices = Invoice.objects.filter(store=store, created_by=user, status=Invoice.Status.PAID, created_at__date__gte=curr_start, created_at__date__lte=curr_end)
        prev_invoices = Invoice.objects.filter(store=store, created_by=user, status=Invoice.Status.PAID, created_at__date__gte=prev_start, created_at__date__lte=prev_end)

        curr_agg = curr_invoices.aggregate(
            total_sales=Sum('total_amount'),
            bills_count=Count('id')
        )
        my_sales = curr_agg['total_sales'] or Decimal('0.00')
        my_count = curr_agg['bills_count'] or 0
        my_aov = (my_sales / my_count) if my_count > 0 else Decimal('0.00')

        prev_agg = prev_invoices.aggregate(
            total_sales=Sum('total_amount'),
            bills_count=Count('id')
        )
        prev_sales = prev_agg['total_sales'] or Decimal('0.00')
        sales_growth_pct = compute_growth_pct(my_sales, prev_sales)

        top_medicines = list(
            InvoiceItem.objects.filter(
                store=store,
                invoice__created_by=user,
                invoice__status=Invoice.Status.PAID,
                invoice__created_at__date__gte=curr_start,
                invoice__created_at__date__lte=curr_end
            )
            .values('medicine_name')
            .annotate(
                total_qty=Sum('quantity'),
                total_revenue=Sum('total_price'),
                orders_count=Count('id')
            )
            .order_by('-total_qty')[:10]
        )

        days_data = []
        delta_days = (curr_end - curr_start).days
        step = 1 if delta_days <= 30 else max(1, delta_days // 15)
        d = curr_start
        while d <= curr_end:
            day_invs = curr_invoices.filter(created_at__date=d)
            day_sales = day_invs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
            days_data.append({
                'date': d,
                'date_str': d.strftime('%d %b'),
                'revenue': float(day_sales),
                'profit': 0.0,
                'invoices_count': day_invs.count(),
            })
            d += timedelta(days=step)

        chart_data = build_timeline_points(days_data)

        context.update({
            'my_sales': my_sales,
            'my_count': my_count,
            'my_aov': my_aov,
            'prev_sales': prev_sales,
            'sales_growth_pct': sales_growth_pct,
            'top_medicines': top_medicines,
            'chart_data': chart_data,
            'days_data': days_data,
        })

