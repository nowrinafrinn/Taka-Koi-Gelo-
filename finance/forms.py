from django import forms
from django.utils import timezone

from .models import MonthlyBudget, Transaction


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
