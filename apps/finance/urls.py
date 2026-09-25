"""Finance URLs (mounted at /finance/)."""

from django.urls import path

from . import views

app_name = 'finance'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('reports/', views.reports, name='reports'),
    path('reports/data/', views.report_data, name='report_data'),
    path('reports/export/', views.export_csv, name='export_csv'),

    # Invoices
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/new/', views.invoice_create, name='invoice_create'),
    path('invoices/new/<int:student_pk>/', views.invoice_create, name='invoice_create_for'),
    path('invoices/bulk/', views.bulk_invoice, name='bulk_invoice'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/issue/', views.invoice_issue, name='invoice_issue'),

    # Payments
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/new/', views.payment_create, name='payment_create'),
    path('payments/new/<int:invoice_pk>/', views.payment_create, name='payment_create_for'),
    path('payments/<int:pk>/', views.payment_detail, name='payment_detail'),
    path('payments/<int:pk>/confirm/', views.payment_confirm, name='payment_confirm'),
    path('payments/<int:pk>/reverse/', views.payment_reverse, name='payment_reverse'),

    # Expenses
    path('expenses/', views.expense_list, name='expense_list'),
    path('expenses/new/', views.expense_create, name='expense_create'),
    path('expenses/<int:pk>/', views.expense_detail, name='expense_detail'),
    path('expenses/<int:pk>/edit/', views.expense_edit, name='expense_edit'),

    # Other income & payroll
    path('income/', views.income_list, name='income_list'),
    path('income/new/', views.income_create, name='income_create'),
    path('payroll/', views.payroll_list, name='payroll_list'),
    path('payroll/new/', views.payroll_create, name='payroll_create'),

    # Catalogue & family view
    path('fees/', views.fee_structure, name='fee_structure'),
    path('my-statement/', views.my_statement, name='my_statement'),
]
