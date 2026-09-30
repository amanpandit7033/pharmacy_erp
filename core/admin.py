from django.contrib import admin
from .models import PlatformSetting

admin.site.site_header = "Pharmacy ERP Administration"
admin.site.site_title = "Pharmacy ERP Admin Portal"
admin.site.index_title = "Welcome to Pharmacy ERP System Management"


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = ('brand_name', 'tagline', 'show_login_footer', 'updated_at')
    list_editable = ('show_login_footer',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Branding', {
            'fields': ('brand_name', 'logo_icon', 'tagline')
        }),
        ('Login Footer Settings', {
            'fields': ('show_login_footer', 'footer_text', 'footer_contact_info')
        }),
        ('Outgoing SMTP & Email Configuration', {
            'fields': (
                'smtp_is_enabled', 'send_welcome_email',
                'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password',
                'smtp_use_tls', 'smtp_use_ssl', 'smtp_default_from_email'
            )
        }),
        ('Audit Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        # Platform settings is a singleton
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)
