from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Count, F, Q

from billing.models import Invoice, InvoiceItem
from inventory.models import Batch


def parse_date_range(request):
    """
    Parses date range query parameters into current period and
    equivalent preceding period for growth comparison.
    """
    today = timezone.localdate()
    period = request.GET.get('period', '7days').strip()
    custom_start_str = request.GET.get('start_date', '').strip()
    custom_end_str = request.GET.get('end_date', '').strip()

    if period == 'today':
        curr_start = today
        curr_end = today
        prev_start = today - timedelta(days=1)
        prev_end = today - timedelta(days=1)
        period_label = "Today vs Yesterday"
    elif period == 'this_month':
        curr_start = today.replace(day=1)
        curr_end = today
        # Previous month equivalent
        prev_month_end = curr_start - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)
        elapsed_days = (curr_end - curr_start).days
        prev_end = min(prev_month_start + timedelta(days=elapsed_days), prev_month_end)
        prev_start = prev_month_start
        period_label = "This Month vs Last Month (MDT)"
    elif period == 'last_month':
        this_month_start = today.replace(day=1)
        curr_end = this_month_start - timedelta(days=1)
        curr_start = curr_end.replace(day=1)
        prev_month_end = curr_start - timedelta(days=1)
        prev_start = prev_month_end.replace(day=1)
        period_label = "Last Month vs Prior Month"
    elif period == 'this_year':
        curr_start = today.replace(month=1, day=1)
        curr_end = today
        prev_year_start = curr_start.replace(year=curr_start.year - 1)
        elapsed_days = (curr_end - curr_start).days
        prev_end = prev_year_start + timedelta(days=elapsed_days)
        prev_start = prev_year_start
        period_label = "This Year vs Prior Year (YTD)"
    elif (period == 'custom' or (custom_start_str and custom_end_str and period != 'today' and period != 'this_month' and period != 'last_month' and period != 'this_year' and period != '7days')) and custom_start_str and custom_end_str:
        try:
            curr_start = timezone.datetime.strptime(custom_start_str, '%Y-%m-%d').date()
            curr_end = timezone.datetime.strptime(custom_end_str, '%Y-%m-%d').date()
            if curr_start > curr_end:
                curr_start, curr_end = curr_end, curr_start
            days_count = (curr_end - curr_start).days + 1
            prev_end = curr_start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=days_count - 1)
            period_label = f"{curr_start.strftime('%d %b %Y')} - {curr_end.strftime('%d %b %Y')}"
        except ValueError:
            # Fallback to 7 days on bad format
            period = '7days'
            curr_start = today - timedelta(days=6)
            curr_end = today
            prev_start = today - timedelta(days=13)
            prev_end = today - timedelta(days=7)
            period_label = "Last 7 Days vs Prior 7 Days"
    else:  # default '7days'
        period = '7days'
        curr_start = today - timedelta(days=6)
        curr_end = today
        prev_start = today - timedelta(days=13)
        prev_end = today - timedelta(days=7)
        period_label = "Last 7 Days vs Prior 7 Days"

    return {
        'period': period,
        'curr_start': curr_start,
        'curr_end': curr_end,
        'prev_start': prev_start,
        'prev_end': prev_end,
        'period_label': period_label,
        'custom_start': curr_start.strftime('%Y-%m-%d'),
        'custom_end': curr_end.strftime('%Y-%m-%d'),
    }


def compute_financials(invoices_qs, store=None, date_range=None):
    """
    Computes accurate financial revenue, COGS, gross profit, inventory write-off losses,
    and net earnings for a queryset of invoices.
    """
    rev_agg = invoices_qs.aggregate(
        total_revenue=Sum('total_amount'),
        total_tax=Sum('tax_amount'),
        total_discount=Sum('discount_amount'),
        invoices_count=Count('id')
    )
    revenue = rev_agg['total_revenue'] or Decimal('0.00')
    tax = rev_agg['total_tax'] or Decimal('0.00')
    discount = rev_agg['total_discount'] or Decimal('0.00')
    invoices_count = rev_agg['invoices_count'] or 0
    aov = (revenue / invoices_count) if invoices_count > 0 else Decimal('0.00')

    # COGS from Line Items
    items = InvoiceItem.objects.filter(invoice__in=invoices_qs)
    cogs_agg = items.aggregate(
        total_cogs=Sum(F('quantity') * F('batch__cost_price'))
    )
    cogs = cogs_agg['total_cogs'] or Decimal('0.00')

    # Gross Profit
    gross_profit = revenue - cogs - discount
    gross_margin_pct = round(float((gross_profit / revenue) * 100), 1) if revenue > 0 else 0.0

    # Disposed / Expired Inventory Loss
    disposed_q = Q(status=Batch.Status.DISPOSED)
    if store:
        disposed_q &= Q(store=store)
    if date_range:
        disposed_q &= Q(updated_at__date__gte=date_range[0], updated_at__date__lte=date_range[1])

    disposed_agg = Batch.objects.filter(disposed_q).aggregate(
        total_loss=Sum(F('quantity') * F('cost_price'))
    )
    inventory_loss = disposed_agg['total_loss'] or Decimal('0.00')

    # Net Estimated Profit
    net_profit = gross_profit - inventory_loss
    net_margin_pct = round(float((net_profit / revenue) * 100), 1) if revenue > 0 else 0.0

    return {
        'revenue': revenue,
        'cogs': cogs,
        'tax': tax,
        'discount': discount,
        'invoices_count': invoices_count,
        'aov': aov,
        'gross_profit': gross_profit,
        'gross_margin_pct': gross_margin_pct,
        'inventory_loss': inventory_loss,
        'net_profit': net_profit,
        'net_margin_pct': net_margin_pct,
    }


def compute_growth_pct(curr_val, prev_val):
    """
    Computes percentage change between two Decimal/float values.
    """
    curr = float(curr_val)
    prev = float(prev_val)
    if prev != 0:
        return round(((curr - prev) / abs(prev)) * 100, 1)
    return 100.0 if curr > 0 else 0.0


def classify_store_performance(revenue_growth_pct, profit_growth_pct, net_profit, inventory_loss, gross_profit):
    """
    Classifies store performance into GROWING, DOWN, AT_RISK, or STABLE.
    """
    if revenue_growth_pct >= 5.0 and profit_growth_pct >= 0:
        return {
            'status': 'GROWING',
            'label': 'Growing',
            'badge': 'bg-emerald-50 text-emerald-700 border-emerald-200',
            'icon': 'trending-up',
            'is_growth': True,
            'is_down': False
        }
    elif revenue_growth_pct < -5.0 or profit_growth_pct < -10.0:
        return {
            'status': 'DOWN',
            'label': 'Down',
            'badge': 'bg-rose-50 text-rose-700 border-rose-200',
            'icon': 'trending-down',
            'is_growth': False,
            'is_down': True
        }
    elif net_profit < 0 or (gross_profit > 0 and inventory_loss > gross_profit):
        return {
            'status': 'AT_RISK',
            'label': 'At Risk',
            'badge': 'bg-amber-50 text-amber-700 border-amber-200',
            'icon': 'alert-triangle',
            'is_growth': False,
            'is_down': True
        }
    else:
        return {
            'status': 'STABLE',
            'label': 'Stable',
            'badge': 'bg-blue-50 text-blue-700 border-blue-200',
            'icon': 'minus',
            'is_growth': False,
            'is_down': False
        }


def build_timeline_points(days_data, width=700, height=200):
    """
    Builds SVG coordinate paths for revenue and profit trend charts
    with generous vertical padding and clean baseline alignment.
    """
    if not days_data:
        return {'rev_line': '', 'profit_line': '', 'rev_area': '', 'max_val': 1.0, 'points': [], 'has_data': False}

    rev_vals = [float(d.get('revenue', 0)) for d in days_data]
    profit_vals = [float(d.get('profit', 0)) for d in days_data]
    raw_max = max(rev_vals + profit_vals + [0.0])
    has_data = raw_max > 0.0
    max_val = raw_max if has_data else 1.0

    n = len(days_data)
    step_x = (width - 60) / max(n - 1, 1)

    # Plot area bounds: top at y=25, baseline at y=155 (giving 45px padding at bottom for dates)
    baseline_y = 155.0
    plot_height = 125.0

    points = []
    for i, d in enumerate(days_data):
        x = round(30 + i * step_x, 1)
        rev = float(d.get('revenue', 0))
        profit = float(d.get('profit', 0))
        y_rev = round(baseline_y - (rev / max_val) * plot_height, 1) if has_data else baseline_y
        y_profit = round(baseline_y - (profit / max_val) * plot_height, 1) if has_data else baseline_y
        points.append({
            'x': x,
            'y_rev': y_rev,
            'y_profit': y_profit,
            'date_str': d.get('date_str', ''),
            'revenue': rev,
            'profit': profit,
            'invoices_count': d.get('invoices_count', 0),
        })

    rev_line = f"M {points[0]['x']} {points[0]['y_rev']}"
    for p in points[1:]:
        rev_line += f" L {p['x']} {p['y_rev']}"

    profit_line = f"M {points[0]['x']} {points[0]['y_profit']}"
    for p in points[1:]:
        profit_line += f" L {p['x']} {p['y_profit']}"

    rev_area = f"{rev_line} L {points[-1]['x']} {baseline_y} L {points[0]['x']} {baseline_y} Z"

    return {
        'rev_line': rev_line,
        'profit_line': profit_line,
        'rev_area': rev_area,
        'max_val': max_val,
        'points': points,
        'has_data': has_data,
        'baseline_y': baseline_y,
    }

