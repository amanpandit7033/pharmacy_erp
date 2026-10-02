import json
import urllib.request
import urllib.error
import logging
from core.models import PlatformSetting

logger = logging.getLogger(__name__)


def format_phone_e164(phone: str) -> str:
    """
    Formats phone numbers to pure digits.
    For standard 10-digit Indian numbers, prepends '91'.
    """
    if not phone:
        return ""
    digits = "".join(filter(str.isdigit, str(phone)))
    if len(digits) == 10:
        return "91" + digits
    if digits.startswith("0") and len(digits) == 11:
        return "91" + digits[1:]
    return digits


def send_invoice_whatsapp(invoice, request=None) -> tuple[bool, str]:
    """
    Dispatches a WhatsApp invoice template message via waba.azmobia.com.
    Resolves API key dynamically based on invoice.store.whatsapp_service_type:
      - 'default': Uses platform master API key from PlatformSetting.
      - 'own': Uses store.whatsapp_api_key.
    """
    store = getattr(invoice, 'store', None)
    if not store:
        return False, "Invoice has no associated pharmacy store."

    platform_settings = PlatformSetting.get_settings()
    if not platform_settings.waba_is_enabled:
        return False, "WhatsApp invoice dispatch is currently disabled in Platform Settings."

    # 1. Resolve API key dynamically based on sending type
    api_key = store.get_whatsapp_api_key()
    if not api_key:
        if store.whatsapp_service_type == store.WhatsAppGatewayType.OWN:
            return False, f"Store '{store.name}' is set to use its own API key, but no WhatsApp API key is configured."
        return False, "Platform Default WhatsApp API key is not configured. Please add it in Super Admin Platform Settings."

    # 2. Format recipient phone
    recipient_phone = format_phone_e164(invoice.customer_phone)
    if not recipient_phone or len(recipient_phone) < 10:
        return False, f"Customer phone number '{invoice.customer_phone}' is missing or invalid."

    # 3. Resolve Media URL & Filename
    # Construct absolute URL to downloadable invoice PDF
    base_url = "https://erp.azmobia.com"
    if request:
        host = request.get_host().lower()
        if '127.0.0.1' in host or 'localhost' in host:
            # On local dev, waba.azmobia.com cannot reach 127.0.0.1,
            # and production erp.azmobia.com does not have this local invoice ID.
            # Fall back to a valid public sample PDF so local developer testing succeeds!
            header_media_url = "https://pdfobject.com/pdf/sample.pdf"
        else:
            base_url = request.build_absolute_uri('/')[:-1]
            header_media_url = f"{base_url}/billing/invoices/{invoice.pk}/pdf/"
    else:
        header_media_url = f"{base_url}/billing/invoices/{invoice.pk}/pdf/"
    
    filename = f"{invoice.invoice_number}.pdf"

    # 4. Prepare Variables
    # Template:
    # Dear *{{1}}*,
    # Thank you for your purchase from *{{2}}*.
    # Your invoice is now ready and attached for your reference.
    # Invoice No: *{{3}}*
    # Invoice Amount: *{{4}}/-*
    # Invoice Date: *{{5}}*
    # Thank you for your business and trust.
    customer_name = (invoice.customer_name or "Customer").strip()
    if customer_name.lower() in ["walk-in customer", "walk in customer", "walk-in", "walkin", "valued customer"]:
        customer_name = "Customer"
    store_name = (store.name or "Pharmacy").strip()
    invoice_no = str(invoice.invoice_number).strip()
    invoice_amount = f"{invoice.total_amount:.2f}"
    invoice_date = invoice.created_at.strftime("%d-%m-%Y") if invoice.created_at else ""

    variables = [customer_name, store_name, invoice_no, invoice_amount, invoice_date]

    # 5. Build Payload
    api_url = (platform_settings.waba_api_url or "http://waba.azmobia.com/api/v1/messages/send-template/").strip()
    payload = {
        "recipient_phone": recipient_phone,
        "language": (platform_settings.waba_language or "en_US").strip(),
        "template_name": (platform_settings.waba_template_name or "welcome_message").strip(),
        "header_media_url": header_media_url,
        "filename": filename,
        "variables": variables,
    }

    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            api_url,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "PharmacyERP/1.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp_body = resp.read().decode('utf-8', errors='ignore')
            logger.info("WABA response for %s: %s", invoice_no, resp_body)
            return True, f"WhatsApp bill sent successfully to +{recipient_phone}."
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='ignore')
        logger.error("WABA HTTP error %s for %s: %s", e.code, invoice_no, err_msg)
        return False, f"WhatsApp Gateway rejected request ({e.code}): {err_msg[:200]}"
    except Exception as e:
        logger.error("WABA dispatch failed for %s: %s", invoice_no, str(e))
        return False, f"Failed to connect to WhatsApp Gateway: {str(e)}"
