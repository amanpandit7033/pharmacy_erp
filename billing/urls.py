from django.urls import path
from billing import views

app_name = 'billing'

urlpatterns = [
    path('pos/', views.POSView.as_view(), name='pos'),
    path('invoices/', views.InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/<int:pk>/', views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<int:pk>/pdf/', views.InvoicePDFView.as_view(), name='invoice_pdf'),
    path('invoices/<int:pk>/print/', views.InvoicePDFView.as_view(), name='invoice_print'),
    path('invoices/<int:pk>/thermal/', views.InvoiceThermalPrintView.as_view(), name='invoice_thermal'),
    path('invoices/<int:pk>/cancel/', views.InvoiceCancelView.as_view(), name='invoice_cancel'),
    path('invoices/<int:pk>/whatsapp/', views.InvoiceWhatsAppSendView.as_view(), name='invoice_whatsapp'),

    # Daily Expenses Tracking (Store Admin)
    path('expenses/', views.ExpenseListView.as_view(), name='expense_list'),
    path('expenses/create/', views.ExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/<int:pk>/edit/', views.ExpenseUpdateView.as_view(), name='expense_edit'),
    path('expenses/<int:pk>/delete/', views.ExpenseDeleteView.as_view(), name='expense_delete'),
]

