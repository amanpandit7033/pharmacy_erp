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


def send_invoice_via_scanned_gateway(invoice, store, platform_settings, recipient_phone, header_media_url, filename) -> tuple[bool, str]:
    """
    Dispatches invoice PDF directly from the store's linked WhatsApp number via Multi-Device Gateway.
    Uses POST /api/send (with type='media') or /api/send-button for rich interactive card.
    """
    gw_url = (platform_settings.whatsapp_gateway_url or '').rstrip('/')
    gw_key = platform_settings.whatsapp_gateway_api_key or ''
    instance_id = store.whatsapp_instance_id

    if not gw_url or not gw_key:
        return False, "WhatsApp Gateway IP/URL or Master API Key is not configured in Admin Settings."

    customer_name = (invoice.customer_name or "Customer").strip()
    if customer_name.lower() in ["walk-in customer", "walk in customer", "walk-in", "walkin", "valued customer"]:
        customer_name = "Valued Customer"

    store_name = (store.name or "Pharmacy").strip()
    invoice_no = str(invoice.invoice_number).strip()
    total_amount = f"{invoice.total_amount:.2f}"
    currency = getattr(store, 'currency', 'Rs.') or 'Rs.'

    caption_text = (
        f"Dear *{customer_name}*,\n\n"
        f"Thank you for visiting *{store_name}*!\n"
        f"Your tax invoice *#{invoice_no}* for *{currency}{total_amount}* has been generated.\n\n"
        f"📄 The detailed PDF invoice is attached above for your reference.\n"
        f"For any dosage queries or refill support, feel free to reply directly to this number.\n\n"
        f"Get well soon!"
    )

    # Endpoint: POST /api/send (type=media)
    dispatch_url = f"{gw_url}/api/send"
    payload = {
        "access_token": gw_key,
        "instance_id": instance_id,
        "number": recipient_phone,
        "type": "media",
        "media_url": header_media_url,
        "filename": filename,
        "message": caption_text
    }

    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            dispatch_url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PharmacyERP/1.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode('utf-8', errors='ignore')
            logger.info("Custom WhatsApp Gateway response for %s: %s", invoice_no, resp_body)
            phone_tag = f" from your linked number (+{store.whatsapp_phone_connected})" if store.whatsapp_phone_connected else ""
            return True, f"WhatsApp bill sent successfully to +{recipient_phone}{phone_tag}."
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='ignore')
        logger.error("Custom Gateway HTTP error %s for %s: %s", e.code, invoice_no, err_msg)
        return False, f"WhatsApp Gateway rejected request ({e.code}): {err_msg[:200]}"
    except Exception as e:
        logger.error("Custom Gateway dispatch failed for %s: %s", invoice_no, str(e))
        return False, f"Failed to connect to WhatsApp Gateway: {str(e)}"


def send_invoice_whatsapp(invoice, request=None) -> tuple[bool, str]:
    """
    Dispatches invoice PDF via WhatsApp.
    Priority 1: If store has has_custom_whatsapp_scan=True and whatsapp_instance_id is active,
                dispatches from the store's OWN scanned WhatsApp number.
    Priority 2: Otherwise, falls back to the WABA Cloud API template dispatch.
    """
    store = getattr(invoice, 'store', None)
    if not store:
        return False, "Invoice has no associated pharmacy store."

    platform_settings = PlatformSetting.get_settings()

    # 1. Format recipient phone
    recipient_phone = format_phone_e164(invoice.customer_phone)
    if not recipient_phone or len(recipient_phone) < 10:
        return False, f"Customer phone number '{invoice.customer_phone}' is missing or invalid."

    # 2. Resolve Media URL & Filename
    base_url = "https://erp.azmobia.com"
    if request:
        host = request.get_host().lower()
        if '127.0.0.1' in host or 'localhost' in host:
            # On local dev, external gateways cannot reach 127.0.0.1.
            # Use public valid PDF sample so developer testing succeeds!
            header_media_url = "https://pdfobject.com/pdf/sample.pdf"
        else:
            base_url = request.build_absolute_uri('/')[:-1]
            header_media_url = f"{base_url}/billing/invoices/{invoice.pk}/pdf/"
    else:
        header_media_url = f"{base_url}/billing/invoices/{invoice.pk}/pdf/"

    filename = f"{invoice.invoice_number}.pdf"

    # PRIORITY 1: Store Own Scanned WhatsApp Number
    if store.has_custom_whatsapp_scan and store.whatsapp_instance_id:
        return send_invoice_via_scanned_gateway(
            invoice, store, platform_settings, recipient_phone, header_media_url, filename
        )

    # PRIORITY 2: Fallback to Meta WABA Cloud API
    if not platform_settings.waba_is_enabled:
        return False, "WhatsApp invoice dispatch is currently disabled in Platform Settings."

    api_key = store.get_whatsapp_api_key()
    if not api_key:
        if store.whatsapp_service_type == store.WhatsAppGatewayType.OWN:
            return False, f"Store '{store.name}' is set to use its own API key, but no WhatsApp API key is configured."
        return False, "Platform Default WhatsApp API key is not configured. Please add it in Super Admin Platform Settings."

    customer_name = (invoice.customer_name or "Customer").strip()
    if customer_name.lower() in ["walk-in customer", "walk in customer", "walk-in", "walkin", "valued customer"]:
        customer_name = "Customer"
    store_name = (store.name or "Pharmacy").strip()
    invoice_no = str(invoice.invoice_number).strip()
    invoice_amount = f"{invoice.total_amount:.2f}"
    invoice_date = invoice.created_at.strftime("%d-%m-%Y") if invoice.created_at else ""

    variables = [customer_name, store_name, invoice_no, invoice_amount, invoice_date]

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
