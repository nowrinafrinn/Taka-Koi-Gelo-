import datetime

from django import forms
from django.utils import timezone

from .models import GoalContribution, MonthlyBudget, SavingsGoal, Transaction
from .services import ZERO, goal_balance, spendable_for_goals
from .templatetags.money import taka


class BudgetForm(forms.ModelForm):
    """Only the limit is editable. The view decides the user and month."""

    class Meta:
        model = MonthlyBudget
        fields = ['limit']
        widgets = {'limit': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'inputmode': 'decimal'})}
        labels = {'limit': 'Spending limit for this month (৳)'}


class TransactionForm(forms.ModelForm):
    """Add/edit form for one kind of transaction.

    The kind (income or expense) and the owner come from the view, never from
    submitted data, so a user cannot post someone else's user id or switch
    an expense into income by editing the HTML.
    """

    class Meta:
        model = Transaction
        fields = ['amount', 'category', 'payment_method', 'date', 'note']
        widgets = {
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'inputmode': 'decimal'}),
            'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'note': forms.TextInput(attrs={'placeholder': 'e.g. Lunch at the canteen'}),
        }
        labels = {'amount': 'Amount (৳)'}

    def __init__(self, *args, kind, user, **kwargs):
        super().__init__(*args, **kwargs)
        # Set these on the instance *before* validation, so the model's
        # clean() can check the category against the kind.
        self.instance.kind = kind
        self.instance.user = user

        allowed = Transaction.INCOME_CATEGORIES if kind == Transaction.Kind.INCOME else Transaction.EXPENSE_CATEGORIES
        self.fields['category'].choices = [
            (value, label) for value, label in Transaction.Category.choices if value in allowed
        ]

        today = timezone.localdate()
        self.fields['date'].widget.attrs['max'] = today.isoformat()
        if not self.instance.pk:
            self.fields['date'].initial = today

        payment = self.fields['payment_method']
        note = self.fields['note'].widget
        if kind == Transaction.Kind.INCOME:
            payment.label = 'Received via (optional)'
            payment.choices = [('', 'Not specified'), *Transaction.PaymentMethod.choices]
            note.attrs['placeholder'] = 'e.g. October tuition from Class 8 student'
        else:
            payment.label = 'Paid with'
            payment.required = True
            # No empty option: expenses must pick one.
            payment.choices = Transaction.PaymentMethod.choices


class StatsPeriodForm(forms.Form):
    """GET parameters of the stats page: ?view=month|year&year=YYYY&month=M.

    Anything missing or invalid falls back to the current month, so a bad
    bookmark or hand-edited URL shows a sensible page instead of an error.
    """

    VIEW_CHOICES = [('month', 'Month'), ('year', 'Year')]
    MONTH_CHOICES = [(i, datetime.date(2000, i, 1).strftime('%B')) for i in range(1, 13)]

    view = forms.ChoiceField(choices=VIEW_CHOICES, required=False)
    year = forms.TypedChoiceField(coerce=int, required=False)
    month = forms.TypedChoiceField(coerce=int, choices=MONTH_CHOICES, required=False)

    def __init__(self, *args, first_year, today, **kwargs):
        super().__init__(*args, **kwargs)
        self.today = today
        self.fields['year'].choices = [(y, y) for y in range(today.year, first_year - 1, -1)]

    def period(self):
        """(view, year, month), always valid and never in the future."""
        data = self.cleaned_data if self.is_valid() else {}
        view = data.get('view') or 'month'
        year = data.get('year') or self.today.year
        month = data.get('month') or (self.today.month if year == self.today.year else 12)
        if (year, month) > (self.today.year, self.today.month):
            month = self.today.month
        return view, year, month


class TransactionFilterForm(forms.Form):
    """Validates the GET parameters of the transaction list."""

    kind = forms.ChoiceField(choices=[('', 'All types'), *Transaction.Kind.choices], required=False, label='Type')
    category = forms.ChoiceField(choices=[('', 'All categories'), *Transaction.Category.choices], required=False)
    start = forms.DateField(required=False, label='From', widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(required=False, label='To', widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start'), cleaned.get('end')
        if start and end and start > end:
            raise forms.ValidationError('"From" must be on or before "To".')
        return cleaned

    def apply(self, queryset):
        """Narrow a queryset using the validated filters."""
        data = self.cleaned_data
        if data.get('kind'):
            queryset = queryset.filter(kind=data['kind'])
        if data.get('category'):
            queryset = queryset.filter(category=data['category'])
        if data.get('start'):
            queryset = queryset.filter(date__gte=data['start'])
        if data.get('end'):
            queryset = queryset.filter(date__lte=data['end'])
        return queryset


class SavingsGoalForm(forms.ModelForm):
    """Name, target and optional date. The owner comes from the view."""

    class Meta:
        model = SavingsGoal
        fields = ['name', 'target_amount', 'target_date']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. New phone'}),
            'target_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'inputmode': 'decimal'}),
            'target_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }
        labels = {'target_amount': 'Target amount (৳)', 'target_date': 'Target date (optional)'}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.user = user

    def clean_name(self):
        # The (user, name) unique constraint isn't checked by ModelForm because
        # `user` isn't a form field, so check it here for a friendly message.
        name = self.cleaned_data['name'].strip()
        duplicate = SavingsGoal.objects.filter(user=self.instance.user, name__iexact=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('You already have a goal with this name.')
        return name


class GoalContributionForm(forms.ModelForm):
    """Add or take out, amount, date and note. The goal comes from the URL,
    never from the form. The goal's balance can never go below ৳0."""

    class Meta:
        model = GoalContribution
        fields = ['kind', 'amount', 'date', 'note']
        widgets = {
            'kind': forms.RadioSelect,
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'inputmode': 'decimal'}),
            'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'note': forms.TextInput(attrs={'placeholder': 'e.g. From tuition money'}),
        }
        labels = {'kind': 'Money', 'amount': 'Amount (৳)'}

    def __init__(self, *args, goal, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.goal = goal
        self.fields['kind'].choices = GoalContribution.Kind.choices   # no blank option
        self.fields['kind'].required = False                          # missing means "Added"
        if not self.instance.pk:
            self.fields['kind'].initial = GoalContribution.Kind.DEPOSIT
        today = timezone.localdate()
        self.fields['date'].widget.attrs['max'] = today.isoformat()
        if not self.instance.pk:
            self.fields['date'].initial = today

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('kind') and 'kind' not in self.errors:
            # An edit without `kind` keeps its current direction; a new entry adds money.
            cleaned['kind'] = self.instance.kind if self.instance.pk else GoalContribution.Kind.DEPOSIT
        kind, amount = cleaned.get('kind'), cleaned.get('amount')
        if kind and amount:
            others = goal_balance(self.instance.goal, exclude=self.instance)
            change = -amount if kind == GoalContribution.Kind.WITHDRAWAL else amount
            if others + change < 0:
                if kind == GoalContribution.Kind.WITHDRAWAL:
                    self.add_error('amount', f'You can take out at most {taka(max(others, 0))}: '
                                             'that is all the money in this goal.')
                else:
                    self.add_error('amount', f'Money already taken out of this goal needs at least '
                                             f'{taka(-others)} here.')
            else:
                self._check_spendable(change)
        return cleaned

    def _check_spendable(self, change):
        """Goals can only hold money you have: what goes in can't exceed the
        balance minus what's already in goals. A change that lowers the total
        saved is always allowed, so an over-saved account can be fixed."""
        before = self.instance.signed_amount if self.instance.pk else ZERO   # instance not updated yet
        if change <= before:
            return
        spendable = spendable_for_goals(self.instance.goal.user, exclude=self.instance)
        if change > spendable:
            # `spendable` already ignores this entry, so it's the most this entry can be.
            self.add_error('amount', f'You can add at most {taka(max(spendable, ZERO))}: that’s your spendable money '
                                     '(your balance minus what’s already in goals). Record income first, '
                                     'or take money out of another goal.')
