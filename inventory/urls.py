from django.urls import path
from inventory import views

app_name = 'inventory'

urlpatterns = [
    path('medicines/', views.MedicineListView.as_view(), name='medicine_list'),
    path('medicines/create/', views.MedicineCreateView.as_view(), name='medicine_create'),
    path('medicines/<int:pk>/', views.MedicineDetailView.as_view(), name='medicine_detail'),
    path('medicines/<int:pk>/edit/', views.MedicineUpdateView.as_view(), name='medicine_edit'),
    path('medicines/<int:pk>/delete/', views.MedicineDeleteView.as_view(), name='medicine_delete'),
    
    # Batches
    path('medicines/<int:medicine_pk>/batches/create/', views.BatchCreateView.as_view(), name='batch_create'),
    path('batches/<int:pk>/edit/', views.BatchUpdateView.as_view(), name='batch_edit'),
    path('batches/<int:pk>/delete/', views.BatchDeleteView.as_view(), name='batch_delete'),
    path('batches/<int:pk>/quarantine/', views.BatchQuarantineActionView.as_view(), name='batch_quarantine_action'),

    # Expiry Watchlist & Quarantine Hub
    path('expiry-watch/', views.ExpiryWatchListView.as_view(), name='expiry_watch'),
    path('expiry-watch/export/', views.ExpiryWatchExportView.as_view(), name='expiry_watch_export'),

    # Categories & Units
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),

    path('units/', views.UnitListView.as_view(), name='unit_list'),
    path('units/create/', views.UnitCreateView.as_view(), name='unit_create'),
    path('units/<int:pk>/edit/', views.UnitUpdateView.as_view(), name='unit_edit'),
    path('units/<int:pk>/delete/', views.UnitDeleteView.as_view(), name='unit_delete'),

    # Master Indian Medicine Catalog (250k+)
    path('master-catalog/', views.MasterCatalogListView.as_view(), name='master_catalog'),
    path('master-catalog/search/', views.MasterMedicineSearchApiView.as_view(), name='master_catalog_search'),
    path('master-catalog/export/', views.MasterCatalogExportView.as_view(), name='master_catalog_export'),
    path('master-catalog/import-csv/', views.MasterCatalogImportCsvView.as_view(), name='master_catalog_import_csv'),
    path('master-catalog/sample-csv/', views.MasterCatalogSampleCsvView.as_view(), name='master_catalog_sample_csv'),
    path('master-catalog/<int:pk>/import/', views.ImportMasterMedicineView.as_view(), name='master_catalog_import'),

    # Super Admin Moderation for Store-Contributed Medicines
    path('master-catalog/contributions/', views.MasterContributionsListView.as_view(), name='master_contributions'),
    path('master-catalog/contributions/<int:pk>/approve/', views.ApproveMasterContributionView.as_view(), name='master_contribution_approve'),
    path('master-catalog/contributions/<int:pk>/reject/', views.RejectMasterContributionView.as_view(), name='master_contribution_reject'),

    # Super Admin Direct National Catalog Management (Create, Edit, Delete)
    path('master-catalog/create/', views.MasterMedicineCreateView.as_view(), name='master_medicine_create'),
    path('master-catalog/<int:pk>/edit/', views.MasterMedicineUpdateView.as_view(), name='master_medicine_edit'),
    path('master-catalog/<int:pk>/delete/', views.MasterMedicineDeleteView.as_view(), name='master_medicine_delete'),
]
