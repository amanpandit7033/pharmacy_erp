from django.urls import path
from dashboard import views

app_name = 'dashboard'

urlpatterns = [
    path('super-admin/', views.SuperAdminDashboardView.as_view(), name='super_admin_dashboard'),
    path('store-admin/', views.StoreAdminDashboardView.as_view(), name='store_admin_dashboard'),
    path('staff/', views.StaffDashboardView.as_view(), name='staff_dashboard'),
    path('analytics/', views.AnalyticsReportView.as_view(), name='analytics_report'),
]
