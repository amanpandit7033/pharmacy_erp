import logging
from django.core.mail.backends.smtp import EmailBackend
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.urls import reverse

logger = logging.getLogger(__name__)


def get_smtp_backend_and_sender(platform_setting=None):
    """
    Constructs an EmailBackend instance dynamically using PlatformSetting.
    Returns: (backend_instance, from_email, error_message)
    """
    from core.models import PlatformSetting
    if platform_setting is None:
        platform_setting = PlatformSetting.get_settings()

    if not platform_setting.smtp_is_enabled:
        return None, platform_setting.smtp_default_from_email or 'no-reply@azmed.com', "SMTP service is currently disabled in Platform Settings."

    if not platform_setting.smtp_host:
        return None, platform_setting.smtp_default_from_email or 'no-reply@azmed.com', "SMTP Host server is not configured."

    try:
        backend = EmailBackend(
            host=platform_setting.smtp_host.strip(),
            port=int(platform_setting.smtp_port or 587),
            username=platform_setting.smtp_user.strip() if platform_setting.smtp_user else None,
            password=platform_setting.smtp_password.strip() if platform_setting.smtp_password else None,
            use_tls=bool(platform_setting.smtp_use_tls),
            use_ssl=bool(platform_setting.smtp_use_ssl),
            timeout=12,
            fail_silently=False,
        )
        from_email = (
            platform_setting.smtp_default_from_email.strip()
            or platform_setting.smtp_user.strip()
            or f"{platform_setting.brand_name} <noreply@azmed.com>"
        )
        return backend, from_email, None
    except Exception as e:
        logger.error(f"Failed to initialize SMTP backend: {e}")
        return None, 'no-reply@azmed.com', str(e)


def test_smtp_connection(recipient_email, platform_setting=None):
    """
    Sends a test email to verify SMTP configuration.
    Returns (success: bool, message: str).
    """
    from core.models import PlatformSetting
    if platform_setting is None:
        platform_setting = PlatformSetting.get_settings()

    backend, from_email, err = get_smtp_backend_and_sender(platform_setting)
    if err:
        return False, err

    if not recipient_email or '@' not in recipient_email:
        return False, "Please provide a valid recipient email address."

    subject = f"[{platform_setting.brand_name}] SMTP Connection Verification Test"
    context = {
        'brand_name': platform_setting.brand_name,
        'tagline': platform_setting.tagline,
        'recipient_email': recipient_email,
        'smtp_host': platform_setting.smtp_host,
        'smtp_port': platform_setting.smtp_port,
        'use_tls': platform_setting.smtp_use_tls,
        'use_ssl': platform_setting.smtp_use_ssl,
        'footer_text': platform_setting.footer_text,
    }

    try:
        html_content = render_to_string('emails/smtp_test_email.html', context)
    except Exception:
        html_content = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #283891;">{platform_setting.brand_name} - SMTP Test Successful!</h2>
            <p>Your SMTP email configuration is active and working correctly.</p>
            <p><strong>Server:</strong> {platform_setting.smtp_host}:{platform_setting.smtp_port}</p>
            <hr>
            <small>{platform_setting.footer_text}</small>
        </div>
        """

    text_content = strip_tags(html_content)

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[recipient_email],
            connection=backend,
        )
        email.attach_alternative(html_content, "text/html")
        email.send(fail_silently=False)
        return True, f"Test email successfully sent to {recipient_email} via {platform_setting.smtp_host}:{platform_setting.smtp_port}."
    except Exception as e:
        logger.error(f"SMTP Test Error: {e}", exc_info=True)
        return False, f"SMTP Connection Failed: {str(e)}"


def send_store_admin_welcome_email(user, raw_password, request=None):
    """
    Sends a professional onboarding email to a newly created Store Admin.
    Returns (success: bool, message: str).
    """
    from core.models import PlatformSetting
    platform_setting = PlatformSetting.get_settings()

    if not platform_setting.smtp_is_enabled:
        return False, "SMTP is disabled in Platform Settings."

    if not platform_setting.send_welcome_email:
        return False, "Store admin welcome email is turned off in settings."

    if not user.email:
        return False, f"User '{user.username}' does not have an email address."

    backend, from_email, err = get_smtp_backend_and_sender(platform_setting)
    if err:
        return False, err

    # Determine login URL
    if request:
        login_url = request.build_absolute_uri(reverse('accounts:login'))
    else:
        login_url = "https://erp.azmobia.com/accounts/login/"

    store = getattr(user, 'store', None)
    store_name = store.name if store else "Assigned Pharmacy Store"
    store_code = store.code if store else "N/A"
    store_location = f"{store.city}, {store.state}" if store and store.city else "Main Branch"

    subject = f"Welcome to {platform_setting.brand_name} - Store Admin Credentials for {store_name}"

    context = {
        'brand_name': platform_setting.brand_name,
        'tagline': platform_setting.tagline,
        'user': user,
        'full_name': user.get_full_name() or user.username,
        'raw_password': raw_password,
        'login_url': login_url,
        'store_name': store_name,
        'store_code': store_code,
        'store_location': store_location,
        'footer_text': platform_setting.footer_text,
        'footer_contact_info': platform_setting.footer_contact_info,
    }

    try:
        html_content = render_to_string('emails/store_admin_welcome.html', context)
        text_content = strip_tags(html_content)

        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[user.email],
            connection=backend,
        )
        email.attach_alternative(html_content, "text/html")
        email.send(fail_silently=False)
        return True, f"Welcome credentials email sent to {user.email}."
    except Exception as e:
        logger.error(f"Failed to send Store Admin welcome email to {user.email}: {e}", exc_info=True)
        return False, f"Could not deliver email: {str(e)}"
