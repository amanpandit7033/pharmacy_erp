from django.urls import path
from stores import views

app_name = 'stores'

urlpatterns = [
    path('', views.StoreListView.as_view(), name='store_list'),
    path('create/', views.StoreCreateView.as_view(), name='store_create'),
    path('<int:pk>/edit/', views.StoreUpdateView.as_view(), name='store_edit'),
    path('<int:pk>/toggle/', views.StoreToggleActiveView.as_view(), name='store_toggle'),
    path('settings/', views.StoreSettingsView.as_view(), name='settings'),
]
