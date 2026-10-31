from django.urls import path
from stores import views, whatsapp_views

app_name = 'stores'

urlpatterns = [
    path('', views.StoreListView.as_view(), name='store_list'),
    path('create/', views.StoreCreateView.as_view(), name='store_create'),
    path('<int:pk>/edit/', views.StoreUpdateView.as_view(), name='store_edit'),
    path('<int:pk>/toggle/', views.StoreToggleActiveView.as_view(), name='store_toggle'),
    path('<int:pk>/delete/', views.StoreDeleteView.as_view(), name='store_delete'),
    path('settings/', views.StoreSettingsView.as_view(), name='settings'),

    # Dedicated Store WhatsApp Invoice Manager Page
    path('whatsapp/manager/', whatsapp_views.StoreWhatsAppManagerPageView.as_view(), name='whatsapp_manager'),

    # Store Custom WhatsApp Scanning APIs
    path('whatsapp/status/', whatsapp_views.StoreWhatsAppStatusView.as_view(), name='whatsapp_status'),
    path('whatsapp/qrcode/', whatsapp_views.StoreWhatsAppQrCodeView.as_view(), name='whatsapp_qrcode'),
    path('whatsapp/logout/', whatsapp_views.StoreWhatsAppLogoutView.as_view(), name='whatsapp_logout'),
]
