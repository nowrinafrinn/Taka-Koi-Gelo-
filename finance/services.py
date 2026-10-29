"""All money calculations live here, not in views or templates.

Rules used everywhere:
- Available balance = all income ever recorded - all expenses ever recorded.
- "This month" = the calendar month containing today's date in Asia/Dhaka,
  judged by each transaction's own date (not when it was saved).
- Budget remaining = this month's budget limit - this month's expenses.
  It can be negative (over budget).
- Every figure is a Decimal with 2 decimal places. No floats.
"""

import calendar
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import MonthlyBudget, Transaction
from .templatetags.money import taka

CENT = Decimal('0.01')
ZERO = Decimal('0.00')
WARNING_PERCENT = Decimal('80')
RECENT_COUNT = 5


def money(value):
    """Database sums come back as Decimal or None (no rows). Normalise to
    an exact 2-decimal Decimal so every figure behaves the same."""
    if value is None:
        return ZERO
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def percent(part, whole):
    """part / whole as a percentage with 1 decimal place. 0 if whole is 0."""
    if not whole:
        return Decimal('0.0')
    return (part * 100 / whole).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def month_bounds(day):
    """First and last date of the month containing `day`."""
    last_day = calendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last_day)


@dataclass
class CategoryShare:
    category: str
    label: str
    total: Decimal
    percent: Decimal


@dataclass
class BudgetStatus:
    limit: Decimal
    spent: Decimal
    remaining: Decimal       # negative when over budget
    used_percent: Decimal    # can exceed 100
    state: str               # 'ok', 'warning' (>= 80%) or 'over' (> limit)
    days_left: int           # including today

    @property
    def overspent(self):
        """How far over the limit, as a positive amount (0 if not over)."""
        return max(-self.remaining, ZERO)

    @property
    def bar_percent(self):
        """Progress-bar width, capped at 100 so the bar never overflows."""
        return min(self.used_percent, Decimal('100'))


@dataclass
class DashboardSummary:
    today: datetime.date
    month_start: datetime.date
    balance: Decimal
    month_income: Decimal
    month_expenses: Decimal
    budget: BudgetStatus | None
    categories: list[CategoryShare]
    recent: list[Transaction]
    month_expense_count: int = 0
    insights: list[str] = field(default_factory=list)

    @property
    def month_net(self):
        return self.month_income - self.month_expenses

    @property
    def has_transactions(self):
        return bool(self.recent)


def get_budget_status(budget, spent, today):
    if budget is None:
        return None
    limit = money(budget.limit)
    used = percent(spent, limit)
    if spent > limit:
        state = 'over'
    elif spent * 100 >= limit * WARNING_PERCENT:
        # Exact comparison, not the rounded percentage: 79.9998% is not 80%.
        state = 'warning'
    else:
        state = 'ok'
    _, month_end = month_bounds(today)
    return BudgetStatus(
        limit=limit,
        spent=spent,
        remaining=limit - spent,
        used_percent=used,
        state=state,
        days_left=(month_end - today).days + 1,
    )


def build_insights(summary):
    """A few plain, true statements. Nothing is estimated or invented."""
    insights = []

    if summary.categories:
        top = summary.categories[0]
        insights.append(
            f'{top.label} took the biggest share this month: {taka(top.total)} '
            f'({top.percent}% of your spending).'
        )

    budget = summary.budget
    if budget:
        if budget.state == 'over':
            insights.append(f'You are {taka(budget.overspent)} over this month’s budget. টাকা কই গেলো?')
        elif budget.remaining == 0:
            insights.append('You have used your whole budget for this month.')
        else:
            per_day = (budget.remaining / budget.days_left).quantize(CENT, rounding=ROUND_DOWN)
            day_word = 'day' if budget.days_left == 1 else 'days'
            insights.append(
                f'{taka(budget.remaining)} left for {budget.days_left} {day_word}: '
                f'about {taka(per_day)} a day.'
            )

    if summary.month_income or summary.month_expenses:
        net = summary.month_net
        if net > 0:
            insights.append(f'So far this month, {taka(net)} more came in than went out.')
        elif net < 0:
            insights.append(f'So far this month, you spent {taka(-net)} more than came in.')
        else:
            insights.append('So far this month, income and spending are exactly even.')

    return insights


def get_dashboard_summary(user, today=None):
    """Everything the dashboard shows, in four queries regardless of how
    many transactions the user has."""
    today = today or timezone.localdate()
    start, end = month_bounds(today)
    this_month = Q(date__range=(start, end))
    income, expense = Q(kind=Transaction.Kind.INCOME), Q(kind=Transaction.Kind.EXPENSE)

    transactions = Transaction.objects.filter(user=user)

    # Query 1: four totals in a single SQL statement using conditional sums.
    totals = transactions.aggregate(
        all_income=Sum('amount', filter=income),
        all_expenses=Sum('amount', filter=expense),
        month_income=Sum('amount', filter=income & this_month),
        month_expenses=Sum('amount', filter=expense & this_month),
        month_expense_count=Count('id', filter=expense & this_month),
    )
    month_expenses = money(totals['month_expenses'])

    # Query 2: this month's spending grouped by category, biggest first.
    rows = (
        transactions.filter(expense & this_month)
        .values('category')
        .annotate(total=Sum('amount'))
        .order_by('-total', 'category')
    )
    categories = [
        CategoryShare(
            category=row['category'],
            label=Transaction.Category(row['category']).label,
            total=money(row['total']),
            percent=percent(money(row['total']), month_expenses),
        )
        for row in rows
    ]

    # Query 3: this month's budget, if one is set.
    budget = MonthlyBudget.objects.filter(user=user, month=start).first()

    # Query 4: latest few transactions.
    recent = list(transactions[:RECENT_COUNT])

    summary = DashboardSummary(
        today=today,
        month_start=start,
        balance=money(totals['all_income']) - money(totals['all_expenses']),
        month_income=money(totals['month_income']),
        month_expenses=month_expenses,
        budget=get_budget_status(budget, month_expenses, today),
        categories=categories,
        recent=recent,
        month_expense_count=totals['month_expense_count'],
    )
    summary.insights = build_insights(summary)
    return summary


def suggested_budget_limit(user, today=None):
    """Prefill for the budget form: the most recent earlier month's limit."""
    today = today or timezone.localdate()
    start, _ = month_bounds(today)
    previous = MonthlyBudget.objects.filter(user=user, month__lt=start).order_by('-month').first()
    return previous.limit if previous else None


# ---------------------------------------------------------------------------
# Wallet visuals
# ---------------------------------------------------------------------------
# The 3D wallet only *illustrates* figures that are already shown as text.
# These rules turn real figures into a few small, explainable visual values.
# Amounts are passed as strings so no float ever represents money.

# Coins peeking out of the wallet, by all-time available balance (৳).
WALLET_COIN_STEPS = [
    (Decimal('500'), 1),
    (Decimal('2000'), 2),
    (Decimal('5000'), 3),
    (Decimal('15000'), 4),
]
WALLET_MAX_COINS = 5
MAX_SPENT_COINS = 8
WALLET_EVENTS = {Transaction.Kind.INCOME, Transaction.Kind.EXPENSE}


def wallet_coin_count(balance):
    """0 coins when the balance is zero or negative, up to 5 when healthy."""
    if balance <= 0:
        return 0
    for limit, coins in WALLET_COIN_STEPS:
        if balance < limit:
            return coins
    return WALLET_MAX_COINS


def wallet_visuals(summary, event=None):
    """Data for the 3D wallet, embedded in the page with json_script."""
    budget = summary.budget
    ring = None
    if budget:
        fraction = min(budget.used_percent / 100, Decimal('1')).quantize(Decimal('0.001'))
        ring = {'fraction': str(fraction), 'state': budget.state}
    return {
        'coins': wallet_coin_count(summary.balance),
        'spentCoins': min(summary.month_expense_count, MAX_SPENT_COINS),
        'budgetRing': ring,
        'event': event if event in WALLET_EVENTS else None,
    }


# ---------------------------------------------------------------------------
# Monthly stats
# ---------------------------------------------------------------------------
# One row per calendar month for the last N months (Asia/Dhaka "today").
# Two separate verdicts per month, never mixed:
#   net      = income - expenses   -> "saved" / "overspent" / "even"
#   budget   = expenses > that month's limit -> over_budget (only if a budget existed)

STATS_MONTHS = 12


def add_months(month_start, count):
    """First day of the month `count` months after (or before) month_start."""
    index = month_start.year * 12 + (month_start.month - 1) + count
    return datetime.date(index // 12, index % 12 + 1, 1)


@dataclass
class MonthStat:
    month: datetime.date          # first day of the month
    income: Decimal
    expenses: Decimal
    budget_limit: Decimal | None
    is_current: bool              # the month is still in progress

    @property
    def net(self):
        return self.income - self.expenses

    @property
    def shortfall(self):
        """How much more went out than came in (0 when not overspent)."""
        return max(-self.net, ZERO)

    @property
    def has_data(self):
        return bool(self.income or self.expenses)

    @property
    def verdict(self):
        if not self.has_data:
            return 'empty'
        if self.net > 0:
            return 'saved'
        if self.net < 0:
            return 'overspent'
        return 'even'

    @property
    def over_budget(self):
        return self.budget_limit is not None and self.expenses > self.budget_limit


@dataclass
class StatsSummary:
    months: list[MonthStat]
    saved_months: int
    overspent_months: int
    over_budget_months: int
    budgeted_months: int
    total_income: Decimal
    total_expenses: Decimal
    best_month: MonthStat | None      # highest positive net
    worst_month: MonthStat | None     # most negative net

    @property
    def first_month(self):
        return self.months[0].month

    @property
    def last_month(self):
        return self.months[-1].month

    @property
    def total_net(self):
        return self.total_income - self.total_expenses

    @property
    def has_data(self):
        return any(m.has_data for m in self.months)


def get_monthly_stats(user, today=None, months=STATS_MONTHS):
    """Income, expenses and verdicts for each of the last `months` months.

    Two queries regardless of data size: one grouped by month, one for budgets.
    """
    today = today or timezone.localdate()
    current_start, current_end = month_bounds(today)
    first_start = add_months(current_start, -(months - 1))

    # Query 1: totals per calendar month, using each transaction's own date.
    rows = (
        Transaction.objects.filter(user=user, date__range=(first_start, current_end))
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(
            income=Sum('amount', filter=Q(kind=Transaction.Kind.INCOME)),
            expenses=Sum('amount', filter=Q(kind=Transaction.Kind.EXPENSE)),
        )
        .order_by('month')
    )
    totals = {row['month']: row for row in rows}

    # Query 2: budgets set for those months.
    budgets = dict(
        MonthlyBudget.objects.filter(user=user, month__range=(first_start, current_start))
        .values_list('month', 'limit')
    )

    stats = []
    for i in range(months):
        start = add_months(first_start, i)
        row = totals.get(start, {})
        limit = budgets.get(start)
        stats.append(MonthStat(
            month=start,
            income=money(row.get('income')),
            expenses=money(row.get('expenses')),
            budget_limit=money(limit) if limit is not None else None,
            is_current=start == current_start,
        ))

    positive = [m for m in stats if m.net > 0]
    negative = [m for m in stats if m.net < 0]
    return StatsSummary(
        months=stats,
        saved_months=len(positive),
        overspent_months=len(negative),
        over_budget_months=sum(m.over_budget for m in stats),
        budgeted_months=sum(m.budget_limit is not None for m in stats),
        total_income=sum((m.income for m in stats), ZERO),
        total_expenses=sum((m.expenses for m in stats), ZERO),
        best_month=max(positive, key=lambda m: m.net) if positive else None,
        worst_month=min(negative, key=lambda m: m.net) if negative else None,
    )
