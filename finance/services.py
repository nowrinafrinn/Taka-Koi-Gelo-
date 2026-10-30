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

from django.db.models import Case, Count, F, Q, Sum, When
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import GoalContribution, MonthlyBudget, SavingsGoal, Transaction
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

    @property
    def daily_allowance(self):
        """Budget left / days left (including today), rounded down so it never
        overstates what can be spent. 0 when nothing is left."""
        if self.remaining <= 0:
            return ZERO
        return (self.remaining / self.days_left).quantize(CENT, rounding=ROUND_DOWN)


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
            per_day = budget.daily_allowance
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
# Monthly money insights (stats page)
# ---------------------------------------------------------------------------
# Rules (also covered by tests):
# - Only the user's own transactions; the month comes from each transaction's
#   own `date`, never from when it was saved.
# - Surplus/deficit = recorded income - recorded expenses. A surplus is money
#   left over on paper, not confirmed savings; a deficit means recorded
#   expenses exceeded recorded income, never "high spending" alone.
# - A month with expenses but no recorded income gets no surplus/deficit
#   verdict ("no_income"): we only show what was spent.
# - Over budget stays a separate, existing flag (expenses > that month's limit).


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
    is_current: bool = False      # still in progress
    is_future: bool = False       # has not started yet (year view only)
    contributions: Decimal = ZERO  # put towards savings goals (not an expense)

    @property
    def savings_rate(self):
        return savings_rate(self.contributions, self.income)

    @property
    def net(self):
        return self.income - self.expenses

    @property
    def has_data(self):
        return bool(self.income or self.expenses)

    @property
    def verdict(self):
        if self.is_future:
            return 'future'
        if not self.has_data:
            return 'empty'
        if not self.income:
            return 'no_income'
        if self.net > 0:
            return 'surplus'
        if self.net < 0:
            return 'deficit'
        return 'even'

    @property
    def shortfall(self):
        """Size of a deficit as a positive amount (0 otherwise)."""
        return max(-self.net, ZERO)

    @property
    def over_budget(self):
        return self.budget_limit is not None and self.expenses > self.budget_limit

    @property
    def budget_over_by(self):
        return max(self.expenses - self.budget_limit, ZERO) if self.budget_limit is not None else ZERO

    @property
    def budget_left(self):
        return max(self.budget_limit - self.expenses, ZERO) if self.budget_limit is not None else ZERO


def _month_rows(user, start, end):
    """{month_start: row} with income/expenses for transactions dated start..end. One query."""
    rows = (
        Transaction.objects.filter(user=user, date__range=(start, end))
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(
            income=Sum('amount', filter=Q(kind=Transaction.Kind.INCOME)),
            expenses=Sum('amount', filter=Q(kind=Transaction.Kind.EXPENSE)),
        )
        .order_by('month')
    )
    return {row['month']: row for row in rows}


def _budgets(user, first_month, last_month):
    """{month_start: limit} for budgets in the range. One query."""
    return dict(
        MonthlyBudget.objects.filter(user=user, month__range=(first_month, last_month))
        .values_list('month', 'limit')
    )


@dataclass
class YearComparison:
    year: int
    months: list[MonthStat]                 # always Jan..Dec
    months_in_period: int                   # months that have started (used for the average)
    total_income: Decimal
    total_expenses: Decimal
    average_expenses: Decimal               # total expenses / months_in_period
    highest_spending: MonthStat | None
    highest_surplus: MonthStat | None
    surplus_months: int
    deficit_months: int
    no_income_months: int
    over_budget_months: int
    budgeted_months: int
    total_contributions: Decimal = ZERO

    @property
    def savings_rate(self):
        return savings_rate(self.total_contributions, self.total_income)

    @property
    def net(self):
        return self.total_income - self.total_expenses

    @property
    def shortfall(self):
        return max(-self.net, ZERO)

    @property
    def has_income(self):
        return self.total_income > 0

    @property
    def has_data(self):
        return any(m.has_data for m in self.months)


def get_year_comparison(user, year, today=None):
    """Jan-Dec of `year`. Three queries regardless of data size."""
    today = today or timezone.localdate()
    current_start, _ = month_bounds(today)
    first, last = datetime.date(year, 1, 1), datetime.date(year, 12, 1)
    totals = _month_rows(user, first, datetime.date(year, 12, 31))
    budgets = _budgets(user, first, last)
    saved = contributions_by_month(user, first, datetime.date(year, 12, 31))

    months = []
    for i in range(12):
        start = add_months(first, i)
        row = totals.get(start, {})
        limit = budgets.get(start)
        months.append(MonthStat(
            month=start,
            income=money(row.get('income')),
            expenses=money(row.get('expenses')),
            budget_limit=money(limit) if limit is not None else None,
            is_current=start == current_start,
            is_future=start > current_start,
            contributions=saved.get(start, ZERO),
        ))

    started = [m for m in months if not m.is_future]
    total_expenses = sum((m.expenses for m in started), ZERO)
    spending = [m for m in started if m.expenses > 0]
    surpluses = [m for m in started if m.verdict == 'surplus']
    return YearComparison(
        year=year,
        months=months,
        months_in_period=len(started),
        total_income=sum((m.income for m in started), ZERO),
        total_expenses=total_expenses,
        average_expenses=money(total_expenses / len(started)) if started else ZERO,
        # max() keeps the earliest month on a tie.
        highest_spending=max(spending, key=lambda m: m.expenses) if spending else None,
        highest_surplus=max(surpluses, key=lambda m: m.net) if surpluses else None,
        surplus_months=len(surpluses),
        deficit_months=sum(m.verdict == 'deficit' for m in started),
        no_income_months=sum(m.verdict == 'no_income' for m in started),
        over_budget_months=sum(m.over_budget for m in started),
        budgeted_months=sum(m.budget_limit is not None for m in started),
        total_contributions=sum((m.contributions for m in started), ZERO),
    )


@dataclass
class MonthReport:
    stat: MonthStat
    categories: list[CategoryShare]
    transaction_count: int

    @property
    def start(self):
        return self.stat.month

    @property
    def end(self):
        return month_bounds(self.stat.month)[1]


def get_month_report(user, year, month, today=None):
    """One calendar month in detail. Four queries."""
    today = today or timezone.localdate()
    start = datetime.date(year, month, 1)
    _, end = month_bounds(start)
    transactions = Transaction.objects.filter(user=user, date__range=(start, end))
    expense = Q(kind=Transaction.Kind.EXPENSE)

    totals = transactions.aggregate(
        income=Sum('amount', filter=Q(kind=Transaction.Kind.INCOME)),
        expenses=Sum('amount', filter=expense),
        count=Count('id'),
    )
    expenses = money(totals['expenses'])
    rows = (
        transactions.filter(expense).values('category')
        .annotate(total=Sum('amount')).order_by('-total', 'category')
    )
    categories = [
        CategoryShare(
            category=row['category'],
            label=Transaction.Category(row['category']).label,
            total=money(row['total']),
            percent=percent(money(row['total']), expenses),
        )
        for row in rows
    ]
    limit = MonthlyBudget.objects.filter(user=user, month=start).values_list('limit', flat=True).first()
    current_start, _ = month_bounds(today)
    stat = MonthStat(
        month=start,
        income=money(totals['income']),
        expenses=expenses,
        budget_limit=money(limit) if limit is not None else None,
        is_current=start == current_start,
        is_future=start > current_start,
        contributions=contributions_between(user, start, end),
    )
    return MonthReport(stat=stat, categories=categories, transaction_count=totals['count'])


def first_transaction_year(user, today=None):
    """Earliest year with a transaction (or this year). One query."""
    today = today or timezone.localdate()
    first = Transaction.objects.filter(user=user).order_by('date').values_list('date', flat=True).first()
    return min(first.year, today.year) if first else today.year


# ---------------------------------------------------------------------------
# Savings goals
# ---------------------------------------------------------------------------
# Contributions live in GoalContribution, never in Transaction. They are not
# expenses: they do not change income, expenses, surplus/deficit, the budget
# or the available balance. They are reported on their own, and the savings
# rate is contributions / income x 100 (None, shown as "N/A", without income).
#
# A contribution is either money added to a goal or money taken out of it.
# Amounts are stored positive; every total below is net: added minus taken out.


def signed_amount(prefix=''):
    """+amount for money added, -amount for money taken out (for Sum())."""
    return Case(
        When(**{f'{prefix}kind': GoalContribution.Kind.WITHDRAWAL}, then=-F(f'{prefix}amount')),
        default=F(f'{prefix}amount'),
    )


def savings_rate(contributions, income):
    """Recorded contributions as a % of recorded income, or None if no income.
    A month where more was taken out than added counts as 0%, never negative."""
    if not income:
        return None
    return (max(contributions, ZERO) * 100 / income).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


@dataclass
class GoalProgress:
    goal: SavingsGoal
    contributed: Decimal
    today: datetime.date

    @property
    def target(self):
        return money(self.goal.target_amount)

    @property
    def remaining(self):
        return max(self.target - self.contributed, ZERO)

    @property
    def percent(self):
        """Actual % of the target reached (can exceed 100)."""
        return percent(self.contributed, self.target)

    @property
    def bar_percent(self):
        return min(self.percent, Decimal('100'))

    @property
    def is_complete(self):
        return self.contributed >= self.target

    @property
    def is_overdue(self):
        return bool(self.goal.target_date) and self.goal.target_date < self.today and not self.is_complete


def goal_progress(goal, today=None):
    """Progress for one goal (one query)."""
    total = goal.contributions.aggregate(total=Sum(signed_amount()))['total']
    return GoalProgress(goal=goal, contributed=money(total), today=today or timezone.localdate())


def goal_balance(goal, exclude=None):
    """Money currently in `goal` (added minus taken out), optionally ignoring
    one contribution, e.g. the one being edited or deleted. One query."""
    entries = goal.contributions.all()
    if exclude is not None and exclude.pk:
        entries = entries.exclude(pk=exclude.pk)
    return money(entries.aggregate(total=Sum(signed_amount()))['total'])


def goals_with_progress(user, today=None):
    """(active, completed) lists of GoalProgress. One query for all goals."""
    today = today or timezone.localdate()
    goals = SavingsGoal.objects.filter(user=user).annotate(contributed=Sum(signed_amount('contributions__')))
    progress = [GoalProgress(goal=g, contributed=money(g.contributed), today=today) for g in goals]
    return [p for p in progress if not p.is_complete], [p for p in progress if p.is_complete]


def contributions_between(user, start, end):
    """Total contributed by the user, across all goals, dated start..end. One query."""
    total = GoalContribution.objects.filter(goal__user=user, date__range=(start, end)).aggregate(
        total=Sum(signed_amount()))['total']
    return money(total)


def total_set_aside(user):
    """All contributions ever recorded (for the dashboard). One query."""
    total = GoalContribution.objects.filter(goal__user=user).aggregate(total=Sum(signed_amount()))['total']
    return money(total)


def contributions_by_month(user, start, end):
    """{month_start: total} of contributions dated start..end. One query."""
    rows = (
        GoalContribution.objects.filter(goal__user=user, date__range=(start, end))
        .annotate(month=TruncMonth('date')).values('month')
        .annotate(total=Sum(signed_amount())).order_by('month')
    )
    return {row['month']: money(row['total']) for row in rows}


# ---------------------------------------------------------------------------
# Monthly spending report (rule-based insights)
# ---------------------------------------------------------------------------
# Each insight is a plain statement backed by recorded data. An insight is
# left out when its data is missing (e.g. no expenses last month means no
# "% more than last month"), so there is never a division by zero or a guess.
# Spending and savings insights are kept in separate lists and never mixed.


@dataclass
class Insight:
    text: str
    # Dot colour only: spending 'up' / 'down' / 'same', 'saving' for goal contributions, else 'neutral'.
    tone: str = 'neutral'


@dataclass
class SpendingReport:
    spending: list[Insight]
    savings: list[Insight]

    @property
    def is_empty(self):
        return not (self.spending or self.savings)


def change_percent(current, previous):
    """Whole-number % change from previous to current, or None if previous is 0."""
    if not previous:
        return None
    return ((current - previous) * 100 / previous).quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def _month_label(day, reference):
    """'September', or 'December 2025' when the year differs from the reference month."""
    return f'{day:%B}' if day.year == reference.year else f'{day:%B %Y}'


def _spending_insights(stat, categories, previous_start, previous_expenses):
    this = _month_label(stat.month, stat.month)
    last = _month_label(previous_start, stat.month)
    so_far = ' so far' if stat.is_current else ''
    insights = []

    if not stat.expenses:
        insights.append(Insight(f'No expenses were recorded in {this}{so_far}.'))
        return insights

    change = change_percent(stat.expenses, previous_expenses)
    figures = f'({taka(stat.expenses)} vs {taka(previous_expenses)})'
    if change is None:
        insights.append(Insight(f'No expenses were recorded in {last}, so there is nothing to compare {this} with.'))
    elif stat.expenses > previous_expenses:
        if change >= 1:
            insights.append(Insight(f'You spent {change}% more in {this}{so_far} than in {last} {figures}.', 'up'))
        else:
            insights.append(Insight(f'Your recorded expenses in {this}{so_far} were about the same as in {last}, '
                                    f'slightly higher {figures}.', 'same'))
    elif stat.expenses < previous_expenses:
        if change <= -1 and stat.is_current:
            # A partial month naturally looks lower than a whole one; say so.
            insights.append(Insight(f'So far in {this}, your recorded expenses are {-change}% lower than in {last} '
                                    f'{figures}. The month isn’t over yet.', 'down'))
        elif change <= -1:
            insights.append(Insight(f'Your recorded expenses decreased by {-change}% compared with {last} {figures}.',
                                    'down'))
        else:
            insights.append(Insight(f'Your recorded expenses in {this}{so_far} were about the same as in {last}, '
                                    f'slightly lower {figures}.', 'same'))
    else:
        insights.append(Insight(f'You spent exactly the same in {this}{so_far} as in {last} ({taka(stat.expenses)}).',
                                'same'))

    if categories:
        top_total = categories[0].total
        leaders = [c for c in categories if c.total == top_total]
        if len(leaders) == 1:
            top = leaders[0]
            insights.append(Insight(f'{top.label} was your largest spending category in {this}{so_far}: '
                                    f'{taka(top.total)} ({top.percent}% of expenses).'))
        else:
            names = ' and '.join(c.label for c in leaders) if len(leaders) == 2 else \
                ', '.join(c.label for c in leaders[:-1]) + f' and {leaders[-1].label}'
            insights.append(Insight(f'{names} were tied as your largest spending categories in {this}{so_far}, '
                                    f'at {taka(top_total)} each.'))
    return insights


def _savings_insights(stat, previous_start, previous_contributions):
    this = _month_label(stat.month, stat.month)
    last = _month_label(previous_start, stat.month)
    so_far = ' so far' if stat.is_current else ''
    current = stat.contributions
    insights = []

    if current < 0:
        insights.append(Insight(f'You took {taka(-current)} more out of your savings goals than you put in '
                                f'during {this}{so_far}.'))
        return insights
    if current:
        text = f'You contributed {taka(current)} towards your savings goals in {this}{so_far}'
        if stat.savings_rate is not None:
            text += f', {stat.savings_rate}% of recorded income.'
        else:
            text += '. There was no recorded income to compare it with.'
        insights.append(Insight(text, 'saving'))
        if previous_contributions:
            difference = current - previous_contributions
            if difference > 0:
                insights.append(Insight(f'That is {taka(difference)} more than you contributed in {last}.', 'saving'))
            elif difference < 0:
                insights.append(Insight(f'That is {taka(-difference)} less than you contributed in {last}.'))
            else:
                insights.append(Insight(f'That is the same amount you contributed in {last}.'))
        else:
            insights.append(Insight(f'You made no goal contributions in {last}.'))
    elif previous_contributions:
        insights.append(Insight(f'You made no goal contributions in {this}{so_far}; '
                                f'in {last} you contributed {taka(previous_contributions)}.'))
    return insights


def get_spending_report(user, report):
    """Insights for the month in `report` (a MonthReport). Two extra queries:
    last month's expenses and last month's goal contributions."""
    stat = report.stat
    previous_start = add_months(stat.month, -1)
    _, previous_end = month_bounds(previous_start)
    previous_expenses = money(
        Transaction.objects.filter(
            user=user, kind=Transaction.Kind.EXPENSE, date__range=(previous_start, previous_end),
        ).aggregate(total=Sum('amount'))['total']
    )
    previous_contributions = contributions_between(user, previous_start, previous_end)
    return SpendingReport(
        spending=_spending_insights(stat, report.categories, previous_start, previous_expenses),
        savings=_savings_insights(stat, previous_start, previous_contributions),
    )


# ---------------------------------------------------------------------------
# Spending pace (dashboard)
# ---------------------------------------------------------------------------
# Running total of this month's expenses by day, compared with an even pace
# through the budget (limit x day / days in month) and with last month's
# running total. No projection: only what has been recorded.


@dataclass
class SpendingPace:
    today: datetime.date
    days_in_month: int
    current: list[Decimal]          # running total for days 1..today
    previous: list[Decimal]         # running total for every day of last month
    budget_limit: Decimal | None

    @property
    def day(self):
        return self.today.day

    @property
    def spent(self):
        return self.current[-1] if self.current else ZERO

    @property
    def even_pace_today(self):
        if self.budget_limit is None:
            return None
        return (self.budget_limit * self.day / self.days_in_month).quantize(CENT, rounding=ROUND_HALF_UP)

    @property
    def previous_same_day(self):
        """Last month's running total on the same day number (capped at its last
        day), or None when nothing was spent last month (nothing to compare)."""
        if not any(self.previous):
            return None
        return self.previous[min(self.day, len(self.previous)) - 1]

    @property
    def status(self):
        """'faster' or 'within' the even budget pace; None without a budget."""
        if self.budget_limit is None:
            return None
        return 'faster' if self.spent > self.even_pace_today else 'within'

    @property
    def has_data(self):
        return bool(self.spent) or any(self.previous)


def _running_totals(user, start, end):
    """Running total of expenses for each day start..end. One query."""
    per_day = dict(
        Transaction.objects.filter(user=user, kind=Transaction.Kind.EXPENSE, date__range=(start, end))
        .values('date').annotate(total=Sum('amount')).values_list('date', 'total')
    )
    totals, running = [], ZERO
    for offset in range((end - start).days + 1):
        running += money(per_day.get(start + datetime.timedelta(days=offset)))
        totals.append(running)
    return totals


def get_spending_pace(user, budget_limit=None, today=None):
    """This month up to today vs last month, as running totals. Two queries."""
    today = today or timezone.localdate()
    start, end = month_bounds(today)
    previous_start, previous_end = month_bounds(add_months(start, -1))
    return SpendingPace(
        today=today,
        days_in_month=end.day,
        current=_running_totals(user, start, today),
        previous=_running_totals(user, previous_start, previous_end),
        budget_limit=budget_limit,
    )


# ---------------------------------------------------------------------------
# Spending by category, month by month (year view)
# ---------------------------------------------------------------------------

# Fixed display order (and colour) for expense categories: the order they are
# declared in, so a category never changes colour between months or years.
EXPENSE_CATEGORY_ORDER = [c for c in Transaction.Category if c in Transaction.EXPENSE_CATEGORIES]


@dataclass
class CategoryYear:
    by_month: dict          # {month_start: {category: Decimal}}
    totals: list[CategoryShare]   # whole period, biggest first

    @property
    def has_data(self):
        return bool(self.totals)


def get_category_by_month(user, year, today=None):
    """Expenses per category for each month of `year` up to the current month.
    One query."""
    today = today or timezone.localdate()
    start = datetime.date(year, 1, 1)
    end = min(datetime.date(year, 12, 31), month_bounds(today)[1])
    rows = (
        Transaction.objects.filter(user=user, kind=Transaction.Kind.EXPENSE, date__range=(start, end))
        .annotate(month=TruncMonth('date')).values('month', 'category')
        .annotate(total=Sum('amount')).order_by('month', 'category')
    )
    by_month, per_category = {}, {}
    for row in rows:
        amount = money(row['total'])
        by_month.setdefault(row['month'], {})[row['category']] = amount
        per_category[row['category']] = per_category.get(row['category'], ZERO) + amount
    grand_total = sum(per_category.values(), ZERO)
    totals = sorted(
        (
            CategoryShare(
                category=category,
                label=Transaction.Category(category).label,
                total=total,
                percent=percent(total, grand_total),
            )
            for category, total in per_category.items()
        ),
        key=lambda share: (-share.total, EXPENSE_CATEGORY_ORDER.index(share.category)),
    )
    return CategoryYear(by_month=by_month, totals=totals)


# ---------------------------------------------------------------------------
# Daily spending and payment methods (month view)
# ---------------------------------------------------------------------------


@dataclass
class DaySpend:
    date: datetime.date
    amount: Decimal
    is_future: bool
    level: int = 0          # 0 = nothing, 1-4 = share of the month's biggest day (calendar shading)


@dataclass
class DailySpending:
    days: list[DaySpend]

    @property
    def biggest(self):
        """The day with the most spending (earliest on a tie), or None."""
        spent = [d for d in self.days if d.amount > 0]
        return max(spent, key=lambda d: d.amount) if spent else None

    @property
    def no_spend_days(self):
        """Days that have started and had no recorded expenses."""
        return sum(1 for d in self.days if not d.is_future and not d.amount)

    @property
    def has_data(self):
        return any(d.amount for d in self.days)


def _shade_level(amount, biggest):
    """1-4 by quarter of the month's biggest day, so shading is relative to this month."""
    if not amount:
        return 0
    share = amount / biggest
    return 1 if share <= Decimal('0.25') else 2 if share <= Decimal('0.5') else 3 if share <= Decimal('0.75') else 4


def get_daily_spending(user, year, month, today=None):
    """Expenses for every day of the month. One query."""
    today = today or timezone.localdate()
    start, end = month_bounds(datetime.date(year, month, 1))
    per_day = dict(
        Transaction.objects.filter(user=user, kind=Transaction.Kind.EXPENSE, date__range=(start, end))
        .values('date').annotate(total=Sum('amount')).values_list('date', 'total')
    )
    days = [
        DaySpend(date=start + datetime.timedelta(days=i), amount=money(per_day.get(start + datetime.timedelta(days=i))),
                 is_future=start + datetime.timedelta(days=i) > today)
        for i in range(end.day)
    ]
    biggest = max((d.amount for d in days), default=ZERO)
    for d in days:
        d.level = _shade_level(d.amount, biggest)
    return DailySpending(days=days)


def calendar_weeks(days):
    """Rows of 7 cells (Sunday first, so Friday-Saturday sit together at the
    end); None pads the first and last week."""
    lead = (days[0].date.weekday() + 1) % 7      # Python: Monday=0 ... Sunday=6
    cells = [None] * lead + list(days)
    cells += [None] * (-len(cells) % 7)
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


def get_payment_methods(user, start, end):
    """Expenses by payment method for the period, biggest first. One query."""
    rows = (
        Transaction.objects.filter(user=user, kind=Transaction.Kind.EXPENSE, date__range=(start, end))
        .values('payment_method').annotate(total=Sum('amount')).order_by('-total', 'payment_method')
    )
    rows = [(row['payment_method'], money(row['total'])) for row in rows]
    grand_total = sum((total for _, total in rows), ZERO)
    labels = dict(Transaction.PaymentMethod.choices)
    return [
        CategoryShare(category=method, label=labels.get(method, 'Not specified'), total=total,
                      percent=percent(total, grand_total))
        for method, total in rows
    ]
