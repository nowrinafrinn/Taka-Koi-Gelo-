from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

# Money is always a Decimal with 2 decimal places (poisha). Up to 10 digits
# before the point is far more than any student needs.
MONEY = {'max_digits': 12, 'decimal_places': 2}
MIN_AMOUNT = Decimal('0.01')


class Transaction(models.Model):
    """One income or expense entry. Both kinds share a table so that the
    balance, recent activity and filters are single queries."""

    class Kind(models.TextChoices):
        INCOME = 'income', 'Income'
        EXPENSE = 'expense', 'Expense'

    class Category(models.TextChoices):
        # Income
        POCKET_MONEY = 'pocket_money', 'Pocket money'
        TUITION = 'tuition', 'Tuition'
        PART_TIME = 'part_time', 'Part-time job'
        OTHER_INCOME = 'other_income', 'Other income'
        # Expense
        FOOD = 'food', 'Food'
        TRANSPORT = 'transport', 'Transport'
        SHOPPING = 'shopping', 'Shopping'
        EDUCATION = 'education', 'Education'
        ENTERTAINMENT = 'entertainment', 'Entertainment'
        BILLS = 'bills', 'Bills'
        HEALTH = 'health', 'Health'
        OTHER_EXPENSE = 'other_expense', 'Other'

    INCOME_CATEGORIES = frozenset({
        Category.POCKET_MONEY, Category.TUITION, Category.PART_TIME, Category.OTHER_INCOME,
    })
    EXPENSE_CATEGORIES = frozenset(set(Category) - INCOME_CATEGORIES)

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        BKASH = 'bkash', 'bKash'
        NAGAD = 'nagad', 'Nagad'
        ROCKET = 'rocket', 'Rocket'
        CARD = 'card', 'Card'
        BANK = 'bank', 'Bank transfer'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # deleting a user deletes their records
        related_name='transactions',
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(MIN_AMOUNT)])
    category = models.CharField(max_length=20, choices=Category.choices)
    # Required for expenses, optional for income (e.g. tuition paid via bKash).
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, blank=True)
    # The calendar day the money moved, chosen by the user. Not a timestamp.
    date = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [models.Index(fields=['user', 'date'])]
        constraints = [
            # Last line of defence: even code that skips validation cannot
            # store a zero or negative amount.
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='transaction_amount_positive'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} ৳{self.amount} ({self.get_category_display()}) on {self.date}'

    def clean(self):
        errors = {}

        allowed = self.INCOME_CATEGORIES if self.kind == self.Kind.INCOME else self.EXPENSE_CATEGORIES
        if self.kind and self.category and self.category not in allowed:
            errors['category'] = f'"{self.get_category_display()}" is not a valid {self.get_kind_display().lower()} category.'

        if self.kind == self.Kind.EXPENSE and not self.payment_method:
            errors['payment_method'] = 'Choose how you paid.'

        if self.date and self.date > timezone.localdate():
            errors['date'] = 'The date cannot be in the future.'

        if errors:
            raise ValidationError(errors)


class MonthlyBudget(models.Model):
    """A spending limit for one calendar month. Stored per month so that
    changing this month's limit never rewrites past months."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='budgets',
    )
    # Always the 1st day of the month (normalised in save()).
    month = models.DateField()
    limit = models.DecimalField(**MONEY, validators=[MinValueValidator(MIN_AMOUNT)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-month']
        constraints = [
            models.UniqueConstraint(fields=['user', 'month'], name='one_budget_per_user_per_month'),
            models.CheckConstraint(condition=models.Q(limit__gt=0), name='budget_limit_positive'),
        ]

    def __str__(self):
        return f'{self.month:%B %Y}: ৳{self.limit}'

    def clean(self):
        # Normalise here too: full_clean() checks the unique constraint
        # before save() runs, so the 15th must already be the 1st by then.
        if self.month:
            self.month = self.month.replace(day=1)

    def save(self, *args, **kwargs):
        if self.month:
            self.month = self.month.replace(day=1)
        super().save(*args, **kwargs)


class SavingsGoal(models.Model):
    """Something the user is saving towards, e.g. "New phone, ৳20,000".

    Savings live in their own tables, never in Transaction, so a contribution
    can't be counted as an expense, change the surplus/deficit, or touch the
    budget. See services.py for how totals are reported.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='savings_goals',
    )
    name = models.CharField(max_length=80)
    target_amount = models.DecimalField(**MONEY, validators=[MinValueValidator(MIN_AMOUNT)])
    target_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_goal_name_per_user'),
            models.CheckConstraint(condition=models.Q(target_amount__gt=0), name='goal_target_positive'),
        ]

    def __str__(self):
        return f'{self.name} (৳{self.target_amount})'


class GoalContribution(models.Model):
    """Money the user put towards a goal on a given date.

    Ownership comes from the goal (goal.user); there is deliberately no
    separate user field that could disagree with it.
    """

    class Kind(models.TextChoices):
        DEPOSIT = 'deposit', 'Added'
        WITHDRAWAL = 'withdrawal', 'Taken out'

    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='contributions')
    # The amount is always positive; `kind` says which way the money moved.
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DEPOSIT)
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(MIN_AMOUNT)])
    date = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [models.Index(fields=['goal', 'date'])]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='contribution_amount_positive'),
            models.CheckConstraint(condition=models.Q(kind__in=['deposit', 'withdrawal']),
                                   name='contribution_kind_valid'),
        ]

    def __str__(self):
        direction = 'from' if self.is_withdrawal else 'to'
        return f'৳{self.amount} {direction} {self.goal.name} on {self.date}'

    @property
    def is_withdrawal(self):
        return self.kind == self.Kind.WITHDRAWAL

    @property
    def signed_amount(self):
        """+amount when added to the goal, -amount when taken out."""
        return -self.amount if self.is_withdrawal else self.amount

    def clean(self):
        if self.date and self.date > timezone.localdate():
            raise ValidationError({'date': 'The date cannot be in the future.'})
