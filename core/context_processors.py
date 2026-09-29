def role_template_context(request):
    """
    Context processor injecting role-appropriate base layout path,
    tenant information, and platform branding into all template contexts.
    """
    from core.models import PlatformSetting
    try:
        platform_settings = PlatformSetting.get_settings()
    except Exception:
        platform_settings = None

    if not request.user.is_authenticated:
        return {
            'role_base_layout': 'base.html',
            'current_role': None,
            'current_store': None,
            'platform_settings': platform_settings,
        }

    role = getattr(request.user, 'role', None)
    if role == 'super_admin' or request.user.is_superuser:
        base_layout = 'layouts/base_super_admin.html'
    elif role == 'store_admin':
        base_layout = 'layouts/base_store_admin.html'
    elif role == 'staff':
        base_layout = 'layouts/base_staff.html'
    else:
        base_layout = 'base.html'

    res = {
        'role_base_layout': base_layout,
        'current_role': role,
        'current_store': getattr(request.user, 'store', None),
        'is_impersonating': bool(request.session.get('impersonator_id')),
        'platform_settings': platform_settings,
    }

    if role == 'super_admin' or request.user.is_superuser:
        from inventory.models import MasterMedicine
        res['pending_contributions_count'] = MasterMedicine.objects.filter(submission_status='pending').count()

    return res

