from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import services
from .forms import BudgetForm, TransactionFilterForm, TransactionForm
from .models import MonthlyBudget, Transaction
from .templatetags.money import taka

PAGE_SIZE = 20


def home(request):
    # Public landing page. Logged-in users go straight to their dashboard.
    if request.user.is_authenticated:
        return redirect('finance:dashboard')
    return render(request, 'finance/home.html')


@login_required
def dashboard(request):
    summary = services.get_dashboard_summary(request.user)
    return render(request, 'finance/dashboard.html', {'summary': summary})


@login_required
@require_http_methods(['GET', 'POST'])
def budget_edit(request):
    """Set or change the budget for the current month only."""
    month_start, _ = services.month_bounds(timezone.localdate())
    budget = (
        MonthlyBudget.objects.filter(user=request.user, month=month_start).first()
        or MonthlyBudget(user=request.user, month=month_start)
    )
    initial = {}
    if budget.pk is None:
        # Suggest last month's limit so the user does not retype it.
        initial['limit'] = services.suggested_budget_limit(request.user)

    form = BudgetForm(request.POST or None, instance=budget, initial=initial)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Budget for {month_start:%B} set to {taka(budget.limit)}.')
        return redirect('finance:dashboard')
    return render(request, 'finance/budget_form.html', {'form': form, 'month_start': month_start})


def get_own_transaction(request, pk):
    """The only way views load a single transaction.

    Filtering by user as well as pk means another user's id gives 404, the
    same as an id that does not exist, so we never reveal that it exists.
    """
    return get_object_or_404(Transaction, pk=pk, user=request.user)


@login_required
def transaction_list(request):
    transactions = request.user.transactions.all()

    filter_form = TransactionFilterForm(request.GET or None)
    if filter_form.is_valid():
        transactions = filter_form.apply(transactions)

    page = Paginator(transactions, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'finance/transaction_list.html', {
        'filter_form': filter_form,
        'page': page,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def transaction_create(request, kind):
    form = TransactionForm(request.POST or None, kind=kind, user=request.user)
    if request.method == 'POST' and form.is_valid():
        transaction = form.save()
        messages.success(request, f'{transaction.get_kind_display()} of {taka(transaction.amount)} saved.')
        # Post/Redirect/Get: refreshing the next page never re-submits the form.
        return redirect('finance:transaction_list')
    return render(request, 'finance/transaction_form.html', {'form': form, 'kind': kind, 'is_edit': False})


@login_required
@require_http_methods(['GET', 'POST'])
def transaction_update(request, pk):
    transaction = get_own_transaction(request, pk)
    form = TransactionForm(request.POST or None, instance=transaction, kind=transaction.kind, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Changes saved.')
        return redirect('finance:transaction_list')
    return render(request, 'finance/transaction_form.html', {'form': form, 'kind': transaction.kind, 'is_edit': True})


@login_required
@require_http_methods(['GET', 'POST'])
def transaction_delete(request, pk):
    transaction = get_own_transaction(request, pk)
    if request.method == 'POST':
        transaction.delete()
        messages.success(request, 'Transaction deleted.')
        return redirect('finance:transaction_list')
    # GET only shows a confirmation page; nothing is deleted.
    return render(request, 'finance/transaction_confirm_delete.html', {'transaction': transaction})
