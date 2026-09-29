from django.urls import path
from billing import views

app_name = 'billing'

urlpatterns = [
    path('pos/', views.POSView.as_view(), name='pos'),
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/print/', views.InvoicePrintView.as_view(), name='invoice_print'),
    path('invoices/<int:pk>/thermal/', views.InvoiceThermalPrintView.as_view(), name='invoice_thermal'),
    path('invoices/<int:pk>/cancel/', views.InvoiceCancelView.as_view(), name='invoice_cancel'),
]
