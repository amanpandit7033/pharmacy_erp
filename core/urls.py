from django.urls import path
from core import views

app_name = 'core'

urlpatterns = [
    path('suggestions/', views.SearchSuggestionsView.as_view(), name='suggestions'),
    path('settings/', views.PlatformSettingsView.as_view(), name='platform_settings'),
    path('settings/test-smtp/', views.TestSmtpConnectionView.as_view(), name='test_smtp'),
    path('push/vapid-key/', views.VapidPublicKeyView.as_view(), name='push_vapid_key'),
    path('push/subscribe/', views.PushSubscribeView.as_view(), name='push_subscribe'),
    path('push/unsubscribe/', views.PushUnsubscribeView.as_view(), name='push_unsubscribe'),
    path('notifications/live/', views.LiveNotificationEventsView.as_view(), name='notifications_live'),
]

