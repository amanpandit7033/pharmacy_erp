import json
import logging
import urllib.request
import urllib.error
from django.views import View
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import PlatformSetting
from core.mixins import RoleRequiredMixin
from accounts.models import User

logger = logging.getLogger(__name__)

class StoreWhatsAppManagerPageView(RoleRequiredMixin, View):
    """Dedicated page for Store Admin to manage WhatsApp device connection and QR pairing."""
    allowed_roles = [User.Role.STORE_ADMIN]
    template_name = 'stores/store_whatsapp_manager.html'

    def get(self, request, *args, **kwargs):
        store = request.user.store
        if not store:
            messages.error(request, "No pharmacy store assigned to your account.")
            return redirect('dashboard:store_admin_dashboard')

        if not store.has_custom_whatsapp_scan:
            messages.warning(request, "WhatsApp Number Scanning is currently not enabled for your store. Please contact Super Admin.")
            return redirect('stores:settings')

        return render(request, self.template_name, {
            'store': store
        })





def make_gateway_request(url: str, method: str = 'GET', data: dict = None, headers: dict = None, timeout: int = 10):
    """Utility helper to send JSON / HTTP requests to WhatsApp Gateway."""
    req_headers = {
        'User-Agent': 'PharmacyERP/1.0',
        'Accept': 'application/json'
    }
    if headers:
        req_headers.update(headers)

    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode('utf-8')
        req_headers['Content-Type'] = 'application/json'

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            resp_data = response.read().decode('utf-8', errors='ignore')
            try:
                return response.status, json.loads(resp_data)
            except Exception:
                return response.status, {'raw': resp_data}
    except urllib.error.HTTPError as e:
        err_data = e.read().decode('utf-8', errors='ignore')
        try:
            return e.code, json.loads(err_data)
        except Exception:
            return e.code, {'error': err_data}
    except Exception as e:
        return 500, {'error': str(e)}


class StoreWhatsAppStatusView(RoleRequiredMixin, View):
    """
    Returns current connection status of the store's WhatsApp instance.
    Checks socket status from the gateway and updates store model.
    """
    allowed_roles = [User.Role.STORE_ADMIN]

    def get(self, request, *args, **kwargs):
        store = request.user.store
        if not store:
            return JsonResponse({'success': False, 'message': 'No store assigned.'}, status=400)

        if not store.has_custom_whatsapp_scan:
            return JsonResponse({'success': False, 'message': 'Store own WhatsApp scanning is not permitted by Admin.'}, status=403)

        settings = PlatformSetting.get_settings()
        gw_url = (settings.whatsapp_gateway_url or '').rstrip('/')
        gw_key = settings.whatsapp_gateway_api_key or ''

        if not gw_url or not gw_key:
            return JsonResponse({
                'success': False,
                'status': 'unconfigured',
                'message': 'WhatsApp Gateway is not configured in Platform Settings. Please contact Administrator.'
            })

        if not store.whatsapp_instance_id:
            return JsonResponse({
                'success': True,
                'status': 'not_created',
                'instance_id': None,
                'phone': None,
                'message': 'No instance created yet. Click "Generate QR Code" to begin.'
            })

        # Check status with Gateway: GET /api/instance_status?instance_id=...&access_token=...
        url = f"{gw_url}/api/instance_status?instance_id={store.whatsapp_instance_id}&access_token={gw_key}"
        status_code, resp = make_gateway_request(url, method='GET')

        logger.info("Gateway instance_status for store %s (%s): %s", store.code, status_code, resp)

        is_connected = False
        phone_number = None

        if status_code == 200:
            # Gateway response structure:
            # {
            #   "status": "success",
            #   "instance_id": "...",
            #   "connected": true,
            #   "connection_status": "connected",
            #   "phone_number": "917033150669",
            #   "live_socket_status": "open"
            # }
            conn_flag = resp.get('connected') is True
            conn_status = str(resp.get('connection_status') or resp.get('status') or '').lower()
            socket_status = str(resp.get('live_socket_status') or '').lower()

            if conn_flag or conn_status == 'connected' or socket_status == 'open':
                is_connected = True
                phone_number = resp.get('phone_number') or resp.get('phone') or resp.get('number') or store.whatsapp_phone_connected
                if phone_number and str(phone_number) != str(store.whatsapp_phone_connected):
                    store.whatsapp_phone_connected = str(phone_number)
                    store.save(update_fields=['whatsapp_phone_connected'])
            elif conn_status in ['disconnected', 'disconnected_by_user', 'init', 'connecting']:
                if store.whatsapp_phone_connected and (conn_status.startswith('disconnect') or resp.get('connected') is False):
                    store.whatsapp_phone_connected = None
                    store.save(update_fields=['whatsapp_phone_connected'])

        return JsonResponse({
            'success': True,
            'status': 'connected' if is_connected else 'disconnected',
            'instance_id': store.whatsapp_instance_id,
            'phone': store.whatsapp_phone_connected,
            'gateway_response': resp
        })


class StoreWhatsAppQrCodeView(RoleRequiredMixin, View):
    """
    Creates instance if missing, and fetches the Base64 QR code for pairing.
    """
    allowed_roles = [User.Role.STORE_ADMIN]

    def get(self, request, *args, **kwargs):
        store = request.user.store
        if not store or not store.has_custom_whatsapp_scan:
            return JsonResponse({'success': False, 'message': 'Store WhatsApp QR scanning not permitted.'}, status=403)

        settings = PlatformSetting.get_settings()
        gw_url = (settings.whatsapp_gateway_url or '').rstrip('/')
        gw_key = settings.whatsapp_gateway_api_key or ''

        if not gw_url or not gw_key:
            return JsonResponse({
                'success': False,
                'message': 'WhatsApp Gateway IP/URL or API Key is missing in Platform Settings.'
            }, status=400)

        # Step 1: Ensure store has a unique instance_id
        if not store.whatsapp_instance_id:
            create_url = f"{gw_url}/api/create_instance?access_token={gw_key}"
            code, create_resp = make_gateway_request(create_url, method='POST')
            logger.info("create_instance response for store %s: %s", store.code, create_resp)

            new_instance_id = create_resp.get('instance_id') or create_resp.get('data', {}).get('instance_id')
            if not new_instance_id:
                # If create_instance returns error or doesn't support GET/POST query param, try JSON body
                code, create_resp = make_gateway_request(
                    f"{gw_url}/api/create_instance",
                    method='POST',
                    data={'access_token': gw_key}
                )
                new_instance_id = create_resp.get('instance_id') or create_resp.get('data', {}).get('instance_id')

            if not new_instance_id:
                return JsonResponse({
                    'success': False,
                    'message': f"Failed to generate WhatsApp Instance ID from Gateway: {create_resp}"
                }, status=500)

            store.whatsapp_instance_id = new_instance_id
            store.whatsapp_phone_connected = None
            store.save(update_fields=['whatsapp_instance_id', 'whatsapp_phone_connected'])

        # Step 2: Fetch QR code for this instance
        qr_url = f"{gw_url}/api/get_qrcode?instance_id={store.whatsapp_instance_id}&access_token={gw_key}"
        code, qr_resp = make_gateway_request(qr_url, method='GET')
        logger.info("get_qrcode response for store %s: code=%s, resp=%s", store.code, code, qr_resp)

        # If gateway returned 404 or instance is not found/unauthorized, generate a brand new instance ID
        if code == 404 or (isinstance(qr_resp, dict) and 'not found' in str(qr_resp.get('message', '')).lower()):
            logger.warning("Instance %s not recognized by Gateway. Auto-generating fresh instance ID...", store.whatsapp_instance_id)
            create_url = f"{gw_url}/api/create_instance?access_token={gw_key}"
            c_code, create_resp = make_gateway_request(create_url, method='POST')
            new_instance_id = create_resp.get('instance_id') or create_resp.get('data', {}).get('instance_id')
            if new_instance_id:
                store.whatsapp_instance_id = new_instance_id
                store.whatsapp_phone_connected = None
                store.save(update_fields=['whatsapp_instance_id', 'whatsapp_phone_connected'])
                # Fetch QR with new instance
                qr_url = f"{gw_url}/api/get_qrcode?instance_id={new_instance_id}&access_token={gw_key}"
                code, qr_resp = make_gateway_request(qr_url, method='GET')

        base64_qr = qr_resp.get('base64') or qr_resp.get('data', {}).get('base64') or qr_resp.get('qrcode')
        
        # If socket needs reboot to generate fresh QR
        if not base64_qr:
            reboot_url = f"{gw_url}/api/reboot?instance_id={store.whatsapp_instance_id}&access_token={gw_key}"
            make_gateway_request(reboot_url, method='POST')
            code, qr_resp = make_gateway_request(qr_url, method='GET')
            base64_qr = qr_resp.get('base64') or qr_resp.get('data', {}).get('base64') or qr_resp.get('qrcode')

        if not base64_qr:
            return JsonResponse({
                'success': False,
                'instance_id': store.whatsapp_instance_id,
                'message': 'QR code is not ready yet or instance is initializing. Please retry in 3 seconds.',
                'raw': qr_resp
            })

        return JsonResponse({
            'success': True,
            'instance_id': store.whatsapp_instance_id,
            'qr_code': base64_qr
        })


class StoreWhatsAppLogoutView(RoleRequiredMixin, View):
    """
    Logs out and clears the WhatsApp instance session on the gateway.
    Prepares the instance for clean re-scanning.
    """
    allowed_roles = [User.Role.STORE_ADMIN]

    def post(self, request, *args, **kwargs):
        store = request.user.store
        if not store or not store.has_custom_whatsapp_scan:
            return JsonResponse({'success': False, 'message': 'Operation not permitted.'}, status=403)

        if not store.whatsapp_instance_id:
            return JsonResponse({'success': True, 'message': 'Store already has no active instance.'})

        settings = PlatformSetting.get_settings()
        gw_url = (settings.whatsapp_gateway_url or '').rstrip('/')
        gw_key = settings.whatsapp_gateway_api_key or ''

        # Call gateway reconnect/reset endpoint to delete session
        if gw_url and gw_key:
            # 1. Reconnect/clear session
            reconnect_url = f"{gw_url}/api/reconnect?instance_id={store.whatsapp_instance_id}&access_token={gw_key}"
            make_gateway_request(reconnect_url, method='GET')

            # 2. Reset instance if supported
            reset_url = f"{gw_url}/api/reset_instance?instance_id={store.whatsapp_instance_id}&access_token={gw_key}"
            code, reset_resp = make_gateway_request(reset_url, method='POST')
            logger.info("Gateway reset_instance for %s: %s", store.code, reset_resp)

        # Clear store connected state
        old_inst = store.whatsapp_instance_id
        store.whatsapp_instance_id = None
        store.whatsapp_phone_connected = None
        store.save(update_fields=['whatsapp_instance_id', 'whatsapp_phone_connected'])

        return JsonResponse({
            'success': True,
            'message': f'WhatsApp session for {old_inst} logged out successfully. You can scan a new number anytime.'
        })

