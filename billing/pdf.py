import io
import os
import shutil
import base64
import tempfile
import subprocess
import logging
from decimal import Decimal
from django.template.loader import render_to_string
from billing.utils import amount_to_words

logger = logging.getLogger(__name__)


def find_browser_binary():
    """Locates Chrome or Edge binary on Windows or Linux."""
    env_bin = os.environ.get('CHROME_BIN')
    if env_bin and os.path.exists(env_bin):
        return env_bin

    candidates = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chromium-browser',
        '/usr/bin/chromium',
        '/snap/bin/chromium',
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c

    for name in ['google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium', 'chrome', 'msedge']:
        path = shutil.which(name)
        if path:
            return path
    return None


def generate_invoice_pdf_from_html(invoice) -> bytes | None:
    """
    Renders invoice_print.html directly using Headless Chrome/Edge.
    Produces a 100% identical pixel-perfect PDF matching browser print preview.
    """
    browser_path = find_browser_binary()
    if not browser_path:
        return None

    items = list(invoice.items.select_related('batch__medicine__unit').all())
    target_rows = 10
    blank_rows = range(target_rows - len(items)) if len(items) < target_rows else []

    # Encode logo as data URI so headless browser can load it from temp HTML with zero external request
    logo_data_uri = None
    store = invoice.store
    if store.logo and hasattr(store.logo, 'path') and os.path.exists(store.logo.path):
        try:
            with open(store.logo.path, 'rb') as f:
                raw = f.read()
                mime = 'image/png'
                if store.logo.name.lower().endswith(('.jpg', '.jpeg')):
                    mime = 'image/jpeg'
                elif store.logo.name.lower().endswith('.webp'):
                    mime = 'image/webp'
                logo_data_uri = f'data:{mime};base64,{base64.b64encode(raw).decode("utf-8")}'
        except Exception as e:
            logger.warning("Could not base64 encode logo: %s", e)

    context = {
        'invoice': invoice,
        'items': items,
        'total_quantity': sum(item.quantity for item in items),
        'blank_rows': blank_rows,
        'amount_in_words': amount_to_words(invoice.total_amount),
        'logo_data_uri': logo_data_uri,
        'pdf_mode': True,
    }

    html_content = render_to_string('billing/invoice_print.html', context)

    html_fd, html_path = tempfile.mkstemp(suffix='.html')
    pdf_fd, pdf_path = tempfile.mkstemp(suffix='.pdf')
    os.close(pdf_fd)

    try:
        with os.fdopen(html_fd, 'w', encoding='utf-8') as f:
            f.write(html_content)

        cmd = [
            browser_path,
            '--headless=new',
            '--disable-gpu',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--no-pdf-header-footer',
            f'--print-to-pdf={pdf_path}',
            html_path
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=15)
        if res.returncode == 0 and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            with open(pdf_path, 'rb') as f:
                return f.read()
        else:
            logger.warning("Browser headless print failed (code %s): %s", res.returncode, res.stderr)
    except Exception as e:
        logger.error("Failed to generate PDF via headless browser: %s", e)
    finally:
        if os.path.exists(html_path):
            try:
                os.remove(html_path)
            except OSError:
                pass
        if os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
            except OSError:
                pass

    return None


def generate_invoice_pdf_reportlab(invoice) -> bytes:
    """Fallback ReportLab generator if no headless browser is available."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.units import mm

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm
    )

    styles = getSampleStyleSheet()

    s_store_title = ParagraphStyle('StoreTitle', fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=colors.HexColor('#0F172A'))
    s_store_sub = ParagraphStyle('StoreSub', fontName='Helvetica', fontSize=7.5, leading=10, textColor=colors.HexColor('#475569'))
    s_pill_title = ParagraphStyle('PillTitle', fontName='Helvetica-Bold', fontSize=8.5, leading=11, alignment=1, textColor=colors.white)
    s_pill_sub = ParagraphStyle('PillSub', fontName='Helvetica-Bold', fontSize=6.5, leading=8, alignment=1, textColor=colors.HexColor('#64748B'))
    s_stat_text = ParagraphStyle('StatText', fontName='Helvetica', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#334155'))
    s_stat_right = ParagraphStyle('StatRight', fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, alignment=2, textColor=colors.HexColor('#0F172A'))
    s_meta_lbl = ParagraphStyle('MetaLbl', fontName='Helvetica', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#64748B'))
    s_meta_val = ParagraphStyle('MetaVal', fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, alignment=2, textColor=colors.HexColor('#0F172A'))
    s_th = ParagraphStyle('TableHeader', fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=colors.HexColor('#334155'))
    s_th_center = ParagraphStyle('TableHeaderCenter', fontName='Helvetica-Bold', fontSize=7, leading=9, alignment=1, textColor=colors.HexColor('#334155'))
    s_th_right = ParagraphStyle('TableHeaderRight', fontName='Helvetica-Bold', fontSize=7, leading=9, alignment=2, textColor=colors.HexColor('#334155'))
    s_td = ParagraphStyle('TableBody', fontName='Helvetica', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#1E293B'))
    s_td_bold = ParagraphStyle('TableBodyBold', fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#0F172A'))
    s_td_sub = ParagraphStyle('TableBodySub', fontName='Helvetica', fontSize=6, leading=7.5, textColor=colors.HexColor('#64748B'))
    s_td_center = ParagraphStyle('TableBodyCenter', fontName='Helvetica', fontSize=7.5, leading=9.5, alignment=1, textColor=colors.HexColor('#334155'))
    s_td_right = ParagraphStyle('TableBodyRight', fontName='Helvetica', fontSize=7.5, leading=9.5, alignment=2, textColor=colors.HexColor('#334155'))
    s_td_right_bold = ParagraphStyle('TableBodyRightBold', fontName='Helvetica-Bold', fontSize=7.5, leading=9.5, alignment=2, textColor=colors.HexColor('#0F172A'))
    s_words_title = ParagraphStyle('WordsTitle', fontName='Helvetica-Bold', fontSize=6.5, leading=8, textColor=colors.HexColor('#64748B'))
    s_words_text = ParagraphStyle('WordsText', fontName='Helvetica-BoldOblique', fontSize=7.5, leading=9.5, textColor=colors.HexColor('#0F172A'))
    s_terms_head = ParagraphStyle('TermsHead', fontName='Helvetica-Bold', fontSize=6.5, leading=8, textColor=colors.HexColor('#334155'))
    s_terms_body = ParagraphStyle('TermsBody', fontName='Helvetica', fontSize=6, leading=7.5, textColor=colors.HexColor('#64748B'))
    s_net_lbl = ParagraphStyle('NetLbl', fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.HexColor('#0F172A'))
    s_net_val = ParagraphStyle('NetVal', fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=2, textColor=colors.HexColor('#0F172A'))
    s_sig_title = ParagraphStyle('SigTitle', fontName='Helvetica-Bold', fontSize=6.5, leading=8, alignment=1, textColor=colors.HexColor('#64748B'))
    s_sig_sub = ParagraphStyle('SigSub', fontName='Helvetica', fontSize=7, leading=9, alignment=1, textColor=colors.HexColor('#334155'))
    s_footer_text = ParagraphStyle('FooterText', fontName='Helvetica', fontSize=6.5, leading=8, textColor=colors.HexColor('#94A3B8'))

    story = []
    store = invoice.store
    raw_curr = (store.currency or "Rs.").replace("₹", "Rs.").strip()
    currency = f"{raw_curr} " if raw_curr else "Rs. "

    store_info_elements = [
        Paragraph(store.name.upper(), s_store_title),
        Paragraph(store.full_address or "", s_store_sub),
        Paragraph(f"Ph: <b>{store.phone or '-'}</b>" + (f" | Email: {store.email}" if store.email else ""), s_store_sub),
    ]

    logo_elem = None
    if store.logo and hasattr(store.logo, 'path') and os.path.exists(store.logo.path):
        try:
            logo_elem = Image(store.logo.path, width=16 * mm, height=16 * mm)
        except Exception:
            logo_elem = None

    if logo_elem:
        left_header_table = Table([[logo_elem, store_info_elements]], colWidths=[18 * mm, 107 * mm])
        left_header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        header_left = left_header_table
    else:
        header_left = store_info_elements

    stat_rows = []
    if store.gst_number:
        stat_rows.append([Paragraph("GSTIN:", s_stat_text), Paragraph(store.gst_number, s_stat_right)])
    stat_rows.append([Paragraph("State:", s_stat_text), Paragraph(store.state or "State", s_stat_right)])

    stat_table = Table(stat_rows, colWidths=[20 * mm, 45 * mm])
    stat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
    ]))

    memo_pill_table = Table([[Paragraph("TAX INVOICE / CASH MEMO", s_pill_title)]], colWidths=[65 * mm])
    memo_pill_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0F172A')),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))

    header_right = [
        memo_pill_table,
        Spacer(1, 1 * mm),
        Paragraph("ORIGINAL FOR RECIPIENT", s_pill_sub),
        Spacer(1, 1 * mm),
        stat_table
    ]

    header_table = Table([[header_left, header_right]], colWidths=[125 * mm, 65 * mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 2.5 * mm))

    inv_date_str = invoice.created_at.strftime("%d/%m/%Y, %I:%M %p") if invoice.created_at else "-"
    cashier_name = ""
    if invoice.created_by:
        cashier_name = getattr(invoice.created_by, 'display_name', '') or invoice.created_by.username or "Counter"
    else:
        cashier_name = "Counter"

    meta_left_rows = [
        [Paragraph("Invoice No:", s_meta_lbl), Paragraph(f"<b>{invoice.invoice_number}</b>", s_meta_val)],
        [Paragraph("Date &amp; Time:", s_meta_lbl), Paragraph(inv_date_str, s_meta_val)],
        [Paragraph("Payment Mode:", s_meta_lbl), Paragraph(f"[{invoice.get_payment_method_display()}]", s_meta_val)],
        [Paragraph("Cashier / Billed By:", s_meta_lbl), Paragraph(cashier_name, s_meta_val)],
    ]
    meta_right_rows = [
        [Paragraph("Customer / Patient:", s_meta_lbl), Paragraph(f"<b>{(invoice.customer_name or 'Walk-in Customer').upper()}</b>", s_meta_val)],
        [Paragraph("Phone / Mobile:", s_meta_lbl), Paragraph(invoice.customer_phone or "Walk-in Customer", s_meta_val)],
        [Paragraph("Prescribing Doctor:", s_meta_lbl), Paragraph(invoice.doctor_name or "Self / OTC Dispense", s_meta_val)],
        [Paragraph("Place of Supply:", s_meta_lbl), Paragraph(f"{store.city}, {store.state}", s_meta_val)],
    ]

    meta_left_table = Table(meta_left_rows, colWidths=[35 * mm, 58 * mm])
    meta_left_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 1.2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
    ]))

    meta_right_table = Table(meta_right_rows, colWidths=[35 * mm, 58 * mm])
    meta_right_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 1.2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
    ]))

    meta_card = Table([[meta_left_table, meta_right_table]], colWidths=[95 * mm, 95 * mm])
    meta_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(meta_card)
    story.append(Spacer(1, 2.5 * mm))

    col_widths = [9 * mm, 72 * mm, 16 * mm, 26 * mm, 18 * mm, 12 * mm, 18 * mm, 19 * mm]
    headers = [
        Paragraph("#", s_th_center),
        Paragraph("MEDICINE / DESCRIPTION", s_th),
        Paragraph("PACK", s_th_center),
        Paragraph("BATCH", s_th_center),
        Paragraph("EXP.", s_th_center),
        Paragraph("QTY", s_th_center),
        Paragraph("PRICE", s_th_right),
        Paragraph("TOTAL", s_th_right),
    ]

    table_data = [headers]
    items = list(invoice.items.all().order_by('id'))
    total_qty = 0

    for idx, item in enumerate(items, start=1):
        total_qty += item.quantity
        exp_str = item.expiry_date.strftime("%m/%y") if item.expiry_date else "-"

        desc_para = [Paragraph(f"<b>{item.medicine_name}</b>", s_td)]
        if getattr(item, 'generic_name', None):
            desc_para.append(Paragraph(item.generic_name, s_td_sub))

        table_data.append([
            Paragraph(str(idx), s_td_center),
            desc_para,
            Paragraph(item.unit_name, s_td_center),
            Paragraph(item.batch_number or "-", s_td_center),
            Paragraph(exp_str, s_td_center),
            Paragraph(f"<b>{item.quantity}</b>", s_td_center),
            Paragraph(f"{currency}{item.unit_price:.2f}", s_td_right),
            Paragraph(f"<b>{currency}{item.total_price:.2f}</b>", s_td_right_bold),
        ])

    target_rows = 10
    blank_count = max(0, target_rows - len(items))
    for b_idx in range(blank_count):
        table_data.append([
            Paragraph(str(len(items) + b_idx + 1), ParagraphStyle('Blk', parent=s_td_center, textColor=colors.HexColor('#CBD5E1'))),
            "", "", "", "", "", "", ""
        ])

    footer_row = [
        Paragraph(f"<b>TOTAL ITEMS:</b> {len(items)} &nbsp;|&nbsp; <b>TOTAL QUANTITY:</b> {total_qty} units", s_td_bold),
        "", "", "", "",
        Paragraph(f"<b>{total_qty}</b>", s_td_center),
        Paragraph("<b>GROSS TOTAL:</b>", s_th_right),
        Paragraph(f"<b>{currency}{invoice.subtotal:.2f}</b>", s_td_right_bold),
    ]
    table_data.append(footer_row)

    items_table = Table(table_data, colWidths=col_widths)
    t_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 1.2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, -1), (4, -1)),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F8FAFC')),
        ('LINEABOVE', (0, -1), (-1, -1), 0.75, colors.HexColor('#CBD5E1')),
    ]
    items_table.setStyle(TableStyle(t_style))
    story.append(items_table)
    story.append(Spacer(1, 2.5 * mm))

    words_str = amount_to_words(invoice.total_amount) or "Zero Rupees Only"
    terms_paragraphs = [
        Paragraph("AMOUNT CHARGEABLE (IN WORDS):", s_words_title),
        Paragraph(f"<b><i>{words_str}</i></b>", s_words_text),
        Spacer(1, 2 * mm),
        Paragraph("TERMS &amp; CONDITIONS:", s_terms_head),
        Paragraph("1. Goods once sold will be accepted back only within 7 days with original bill and unbroken seal.", s_terms_body),
        Paragraph("2. Scheduled medications dispensed strictly on valid prescription of a Registered Medical Practitioner.", s_terms_body),
        Paragraph("3. Store medicines in a cool, dry place. Keep all medicines out of reach of children.", s_terms_body),
    ]

    summary_rows = [
        [Paragraph("Subtotal (Before Tax):", s_meta_lbl), Paragraph(f"<b>{currency}{invoice.subtotal:.2f}</b>", s_meta_val)],
    ]
    if invoice.discount_amount > 0:
        summary_rows.append([
            Paragraph("Special Discount:", ParagraphStyle('Disc', parent=s_meta_lbl, textColor=colors.HexColor('#E11D48'))),
            Paragraph(f"-{currency}{invoice.discount_amount:.2f}", ParagraphStyle('DiscVal', parent=s_meta_val, textColor=colors.HexColor('#E11D48')))
        ])
    if invoice.tax_amount > 0:
        summary_rows.append([
            Paragraph("GST / Tax Amount (Included):", s_meta_lbl),
            Paragraph(f"<b>{currency}{invoice.tax_amount:.2f}</b>", s_meta_val)
        ])

    net_box = Table([[Paragraph("NET AMOUNT PAYABLE:", s_net_lbl), Paragraph(f"<b>{currency}{invoice.total_amount:.2f}</b>", s_net_val)]], colWidths=[40 * mm, 33 * mm])
    net_box.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
    ]))

    summary_inner_table = Table(summary_rows, colWidths=[42 * mm, 33 * mm])
    summary_inner_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 1 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    summary_right_elements = [
        summary_inner_table,
        Spacer(1, 2 * mm),
        net_box
    ]

    bottom_card = Table([[terms_paragraphs, summary_right_elements]], colWidths=[112 * mm, 78 * mm])
    bottom_card.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('BACKGROUND', (0, 0), (0, 0), colors.white),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#F8FAFC')),
        ('TOPPADDING', (0, 0), (-1, -1), 2 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2 * mm),
        ('LEFTPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2.5 * mm),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(bottom_card)
    story.append(Spacer(1, 4 * mm))

    sig_customer = [
        Paragraph(invoice.customer_name or "Walk-in Customer", s_sig_sub),
        Spacer(1, 1 * mm),
        Table([[""]], colWidths=[55 * mm], style=[('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8'))]),
        Paragraph("CUSTOMER / PATIENT SIGNATURE", s_sig_title),
    ]
    sig_pharmacist = [
        Paragraph(cashier_name, s_sig_sub),
        Spacer(1, 1 * mm),
        Table([[""]], colWidths=[55 * mm], style=[('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8'))]),
        Paragraph("DISPENSED BY (PHARMACIST)", s_sig_title),
    ]
    sig_store = [
        Paragraph(f"For {store.name}", s_sig_sub),
        Spacer(1, 1 * mm),
        Table([[""]], colWidths=[55 * mm], style=[('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8'))]),
        Paragraph("AUTHORIZED SIGNATORY", s_sig_title),
    ]

    sig_table = Table([[sig_customer, sig_pharmacist, sig_store]], colWidths=[63 * mm, 63 * mm, 64 * mm])
    sig_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(sig_table)
    story.append(Spacer(1, 3 * mm))

    disc_table = Table([[
        Paragraph("Computer Generated Tax Invoice • No signature required under IT Act", s_footer_text),
        Paragraph("<b>Wishing You Good Health! Get Well Soon.</b>", ParagraphStyle('W', parent=s_footer_text, alignment=1, textColor=colors.HexColor('#475569'))),
        Paragraph("Page 1 of 1", ParagraphStyle('P', parent=s_footer_text, alignment=2))
    ]], colWidths=[70 * mm, 70 * mm, 50 * mm])
    disc_table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(disc_table)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_invoice_pdf(invoice) -> bytes:
    """
    Primary entry point:
    1. First attempts to render invoice_print.html using Headless Chrome/Edge.
       This provides a 100% pixel-perfect replica of the browser print screen.
    2. Falls back to ReportLab if no browser binary is installed.
    """
    pdf_bytes = generate_invoice_pdf_from_html(invoice)
    if pdf_bytes:
        return pdf_bytes
    return generate_invoice_pdf_reportlab(invoice)
