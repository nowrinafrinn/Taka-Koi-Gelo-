from django.contrib import admin

from .models import MonthlyBudget, Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['date', 'user', 'kind', 'category', 'amount', 'payment_method']
    list_filter = ['kind', 'category', 'payment_method', 'date']
    search_fields = ['note', 'user__username']
    date_hierarchy = 'date'
    list_select_related = ['user']  # avoid one extra query per row


@admin.register(MonthlyBudget)
class MonthlyBudgetAdmin(admin.ModelAdmin):
    list_display = ['month', 'user', 'limit']
    list_select_related = ['user']
