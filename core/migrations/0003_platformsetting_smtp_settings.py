from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_platformsetting_footer_contact_info_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_is_enabled',
            field=models.BooleanField(default=False, help_text='Enable automated email dispatch (store invitations, credentials, alerts).'),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_host',
            field=models.CharField(blank=True, default='', help_text='SMTP server host (e.g., smtp.gmail.com, smtp.office365.com, smtp.sendgrid.net)', max_length=255),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_port',
            field=models.PositiveIntegerField(default=587, help_text='SMTP server port (typically 587 for TLS or 465 for SSL)'),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_user',
            field=models.CharField(blank=True, default='', help_text='SMTP account username or sender email address.', max_length=255),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_password',
            field=models.CharField(blank=True, default='', help_text='SMTP account password or app-specific application password.', max_length=255),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_use_tls',
            field=models.BooleanField(default=True, help_text='Use TLS connection security (Recommended for port 587).'),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_use_ssl',
            field=models.BooleanField(default=False, help_text='Use SSL connection security (Recommended for port 465).'),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='smtp_default_from_email',
            field=models.CharField(blank=True, default='', help_text="Sender email appearing in 'From:' field (e.g., Azmed ERP <noreply@azmed.com>).", max_length=255),
        ),
        migrations.AddField(
            model_name='platformsetting',
            name='send_welcome_email',
            field=models.BooleanField(default=True, help_text='Automatically send professional onboarding email with login credentials when a store admin is created.'),
        ),
    ]
