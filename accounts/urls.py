from django.urls import path
from accounts import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.UserLoginView.as_view(), name='login'),
    path('logout/', views.UserLogoutView.as_view(), name='logout'),
    path('role-redirect/', views.RoleRedirectView.as_view(), name='role_redirect'),
    path('profile/', views.UserProfileView.as_view(), name='profile'),
    
    # Store admin managing staff
    path('staff/', views.StaffListView.as_view(), name='staff_list'),
    path('staff/create/', views.StaffCreateView.as_view(), name='staff_create'),
    path('staff/<int:pk>/edit/', views.StaffUpdateView.as_view(), name='staff_edit'),
    path('staff/<int:pk>/toggle/', views.StaffToggleActiveView.as_view(), name='staff_toggle'),
    
    # Super admin managing store admins and store staff
    path('store-admins/', views.StoreAdminListView.as_view(), name='store_admin_list'),
    path('store-admins/create/', views.StoreAdminCreateView.as_view(), name='store_admin_create'),
    path('store-admins/<int:pk>/edit/', views.StoreAdminUpdateView.as_view(), name='store_admin_edit'),
    path('store-admins/<int:pk>/resend-email/', views.ResendStoreAdminWelcomeEmailView.as_view(), name='store_admin_resend_email'),
    path('store-staff/', views.AllStaffListView.as_view(), name='all_staff_list'),

    # Impersonation (Login as user without password)
    path('impersonate/<int:pk>/', views.ImpersonateUserView.as_view(), name='impersonate_user'),
    path('impersonate/exit/', views.ExitImpersonationView.as_view(), name='exit_impersonation'),
]
