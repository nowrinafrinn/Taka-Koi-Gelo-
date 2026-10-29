from django.urls import path, register_converter

from . import converters, views
from .models import Transaction

register_converter(converters.IsoDateConverter, 'isodate')

app_name = 'finance'

urlpatterns = [
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('budget/', views.budget_edit, name='budget_edit'),
    path('stats/', views.stats, name='stats'),
    path('stats/day/<isodate:day>/', views.day_detail, name='day_detail'),
    path('transactions/', views.transaction_list, name='transaction_list'),
    # The kind is fixed by the URL, not by a form field the user could edit.
    path('transactions/add/income/', views.transaction_create, {'kind': Transaction.Kind.INCOME}, name='income_create'),
    path('transactions/add/expense/', views.transaction_create, {'kind': Transaction.Kind.EXPENSE}, name='expense_create'),
    path('transactions/<int:pk>/edit/', views.transaction_update, name='transaction_update'),
    path('transactions/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
    path('goals/', views.goal_list, name='goal_list'),
    path('goals/new/', views.goal_create, name='goal_create'),
    path('goals/<int:pk>/', views.goal_detail, name='goal_detail'),
    path('goals/<int:pk>/edit/', views.goal_update, name='goal_update'),
    path('goals/<int:pk>/delete/', views.goal_delete, name='goal_delete'),
    path('goals/<int:pk>/contribute/', views.contribution_create, name='contribution_create'),
    path('goals/contributions/<int:pk>/edit/', views.contribution_update, name='contribution_update'),
    path('goals/contributions/<int:pk>/delete/', views.contribution_delete, name='contribution_delete'),
]
