from django.urls import path
from core import views

app_name = 'core'

urlpatterns = [
    path('suggestions/', views.SearchSuggestionsView.as_view(), name='suggestions'),
    path('settings/', views.PlatformSettingsView.as_view(), name='platform_settings'),
    path('settings/test-smtp/', views.TestSmtpConnectionView.as_view(), name='test_smtp'),
]

