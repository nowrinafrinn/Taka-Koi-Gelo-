from django.urls import path

from . import views
from .models import Transaction

app_name = 'finance'

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('budget/', views.budget_edit, name='budget_edit'),
    path('transactions/', views.transaction_list, name='transaction_list'),
    # The kind is fixed by the URL, not by a form field the user could edit.
    path('transactions/add/income/', views.transaction_create, {'kind': Transaction.Kind.INCOME}, name='income_create'),
    path('transactions/add/expense/', views.transaction_create, {'kind': Transaction.Kind.EXPENSE}, name='expense_create'),
    path('transactions/<int:pk>/edit/', views.transaction_update, name='transaction_update'),
    path('transactions/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
]
