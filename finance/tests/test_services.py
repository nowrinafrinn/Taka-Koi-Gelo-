import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from finance import services
from finance.models import MonthlyBudget, Transaction

User = get_user_model()
D = Decimal
# A fixed "today" so tests never depend on when they run.
TODAY = datetime.date(2026, 10, 20)


def add(user, kind, amount, date=TODAY, category=None):
    if category is None:
        category = 'pocket_money' if kind == 'income' else 'food'
    return Transaction.objects.create(
        user=user, kind=kind, amount=D(amount), category=category,
        payment_method='' if kind == 'income' else 'cash', date=date,
    )


def budget(user, limit, month=TODAY):
    return MonthlyBudget.objects.create(user=user, month=month, limit=D(limit))


class SummaryTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def summary(self, today=TODAY):
        return services.get_dashboard_summary(self.user, today=today)


class EmptyAndZeroTests(SummaryTestCase):
    def test_new_user_gets_zeros_not_errors(self):
        s = self.summary()
        self.assertEqual(s.balance, D('0.00'))
        self.assertEqual(s.month_income, D('0.00'))
        self.assertEqual(s.month_expenses, D('0.00'))
        self.assertIsNone(s.budget)
        self.assertEqual(s.categories, [])
        self.assertEqual(s.recent, [])
        self.assertEqual(s.insights, [])
        self.assertFalse(s.has_transactions)

    def test_all_figures_are_decimals(self):
        add(self.user, 'income', '100')
        s = self.summary()
        for value in (s.balance, s.month_income, s.month_expenses):
            self.assertIsInstance(value, Decimal)

    def test_budget_with_no_spending(self):
        budget(self.user, '5000')
        b = self.summary().budget
        self.assertEqual(b.spent, D('0.00'))
        self.assertEqual(b.remaining, D('5000.00'))
        self.assertEqual(b.used_percent, D('0.0'))
        self.assertEqual(b.state, 'ok')


class BalanceAndMonthTotalsTests(SummaryTestCase):
    def test_balance_is_all_time_and_month_totals_are_this_month_only(self):
        add(self.user, 'income', '10000', date=datetime.date(2026, 8, 5))
        add(self.user, 'expense', '3000', date=datetime.date(2026, 9, 10))
        add(self.user, 'income', '2000')
        add(self.user, 'expense', '500.50')
        s = self.summary()
        self.assertEqual(s.balance, D('8499.50'))      # 10000 - 3000 + 2000 - 500.50
        self.assertEqual(s.month_income, D('2000.00'))
        self.assertEqual(s.month_expenses, D('500.50'))
        self.assertEqual(s.month_net, D('1499.50'))

    def test_balance_can_be_negative(self):
        add(self.user, 'income', '100')
        add(self.user, 'expense', '250')
        self.assertEqual(self.summary().balance, D('-150.00'))

    def test_other_users_data_never_counted(self):
        add(self.other, 'income', '99999')
        add(self.other, 'expense', '5000')
        budget(self.other, '1000')
        s = self.summary()
        self.assertEqual(s.balance, D('0.00'))
        self.assertEqual(s.month_expenses, D('0.00'))
        self.assertIsNone(s.budget)
        self.assertEqual(s.recent, [])


class MonthBoundaryTests(SummaryTestCase):
    def test_first_and_last_day_included_neighbours_excluded(self):
        add(self.user, 'expense', '1', date=datetime.date(2026, 9, 30))   # previous month
        add(self.user, 'expense', '10', date=datetime.date(2026, 10, 1))  # first day
        add(self.user, 'expense', '100', date=datetime.date(2026, 10, 31))  # last day
        s = self.summary(today=datetime.date(2026, 10, 31))
        self.assertEqual(s.month_expenses, D('110.00'))
        self.assertEqual(s.balance, D('-111.00'))

    def test_month_bounds_handles_february_and_leap_years(self):
        self.assertEqual(services.month_bounds(datetime.date(2026, 2, 14))[1], datetime.date(2026, 2, 28))
        self.assertEqual(services.month_bounds(datetime.date(2028, 2, 14))[1], datetime.date(2028, 2, 29))
        self.assertEqual(
            services.month_bounds(datetime.date(2026, 12, 31)),
            (datetime.date(2026, 12, 1), datetime.date(2026, 12, 31)),
        )

    def test_current_month_follows_dhaka_time(self):
        # 19:00 UTC on 31 Oct is 01:00 on 1 Nov in Dhaka, so October
        # spending must no longer count as "this month".
        add(self.user, 'expense', '700', date=datetime.date(2026, 10, 31))
        utc_now = datetime.datetime(2026, 10, 31, 19, 0, tzinfo=datetime.timezone.utc)
        with mock.patch('django.utils.timezone.now', return_value=utc_now):
            s = services.get_dashboard_summary(self.user)
        self.assertEqual(s.month_start, datetime.date(2026, 11, 1))
        self.assertEqual(s.month_expenses, D('0.00'))
        self.assertEqual(s.balance, D('-700.00'))


class DecimalPrecisionTests(SummaryTestCase):
    def test_many_small_amounts_sum_exactly(self):
        # 0.10 cannot be represented exactly as a float; 1000 of them
        # must still total exactly 100.00.
        Transaction.objects.bulk_create([
            Transaction(user=self.user, kind='expense', amount=D('0.10'), category='food',
                        payment_method='cash', date=TODAY)
            for _ in range(1000)
        ])
        self.assertEqual(self.summary().month_expenses, D('100.00'))

    def test_classic_float_trap(self):
        add(self.user, 'income', '0.10')
        add(self.user, 'income', '0.20')
        self.assertEqual(self.summary().balance, D('0.30'))   # not 0.30000000000000004

    def test_large_amounts_keep_paisa(self):
        add(self.user, 'income', '9999999.99')
        add(self.user, 'income', '0.01')
        self.assertEqual(self.summary().balance, D('10000000.00'))


class BudgetTests(SummaryTestCase):
    def test_no_budget_means_none(self):
        add(self.user, 'expense', '100')
        self.assertIsNone(self.summary().budget)

    def test_only_this_months_budget_is_used(self):
        budget(self.user, '9000', month=datetime.date(2026, 9, 1))
        self.assertIsNone(self.summary().budget)

    def test_ok_state(self):
        budget(self.user, '5000')
        add(self.user, 'expense', '1000')
        b = self.summary().budget
        self.assertEqual((b.spent, b.remaining, b.used_percent, b.state), (D('1000.00'), D('4000.00'), D('20.0'), 'ok'))

    def test_warning_starts_at_exactly_80_percent(self):
        budget(self.user, '5000')
        add(self.user, 'expense', '3999.99')
        # 79.9998% displays as 80.0% but has not reached the threshold.
        self.assertEqual(self.summary().budget.state, 'ok')
        add(self.user, 'expense', '0.01')
        self.assertEqual(self.summary().budget.state, 'warning')  # exactly 80%

    def test_exactly_at_limit_is_warning_not_over(self):
        budget(self.user, '5000')
        add(self.user, 'expense', '5000')
        b = self.summary().budget
        self.assertEqual((b.remaining, b.used_percent, b.state), (D('0.00'), D('100.0'), 'warning'))

    def test_overspending_gives_negative_remaining(self):
        budget(self.user, '5000')
        add(self.user, 'expense', '6250.50')
        b = self.summary().budget
        self.assertEqual(b.state, 'over')
        self.assertEqual(b.remaining, D('-1250.50'))
        self.assertEqual(b.overspent, D('1250.50'))
        self.assertEqual(b.used_percent, D('125.0'))
        self.assertEqual(b.bar_percent, D('100'))  # bar is capped

    def test_income_does_not_reduce_budget_usage(self):
        budget(self.user, '5000')
        add(self.user, 'income', '20000')
        add(self.user, 'expense', '1000')
        self.assertEqual(self.summary().budget.spent, D('1000.00'))

    def test_days_left_includes_today(self):
        budget(self.user, '3100')
        self.assertEqual(self.summary(today=datetime.date(2026, 10, 31)).budget.days_left, 1)
        self.assertEqual(self.summary(today=datetime.date(2026, 10, 1)).budget.days_left, 31)

    def test_suggested_limit_comes_from_latest_previous_month(self):
        budget(self.user, '4000', month=datetime.date(2026, 8, 1))
        budget(self.user, '4500', month=datetime.date(2026, 9, 1))
        budget(self.other, '99999', month=datetime.date(2026, 9, 1))
        self.assertEqual(services.suggested_budget_limit(self.user, today=TODAY), D('4500.00'))

    def test_no_suggestion_without_history(self):
        self.assertIsNone(services.suggested_budget_limit(self.user, today=TODAY))


class CategoryBreakdownTests(SummaryTestCase):
    def test_expenses_grouped_biggest_first_with_percentages(self):
        add(self.user, 'expense', '600', category='food')
        add(self.user, 'expense', '150', category='food')
        add(self.user, 'expense', '250', category='transport')
        add(self.user, 'income', '5000', category='tuition')                       # not spending
        add(self.user, 'expense', '999', category='shopping', date=datetime.date(2026, 9, 1))  # last month
        cats = self.summary().categories
        self.assertEqual([(c.category, c.label, c.total, c.percent) for c in cats], [
            ('food', 'Food', D('750.00'), D('75.0')),
            ('transport', 'Transport', D('250.00'), D('25.0')),
        ])


class InsightTests(SummaryTestCase):
    def test_top_category_insight(self):
        add(self.user, 'expense', '750', category='food')
        add(self.user, 'expense', '250', category='transport')
        self.assertIn('Food took the biggest share this month: ৳750.00 (75.0% of your spending).', self.summary().insights)

    def test_daily_allowance_rounds_down(self):
        budget(self.user, '1000')
        add(self.user, 'expense', '0.01')
        # 999.99 left over 12 days (20th..31st) = 83.3325, shown as 83.33
        self.assertIn('৳999.99 left for 12 days: about ৳83.33 a day.', self.summary().insights)

    def test_over_budget_insight(self):
        budget(self.user, '1000')
        add(self.user, 'expense', '1200')
        self.assertTrue(any('৳200.00 over' in text for text in self.summary().insights))

    def test_spent_more_than_came_in(self):
        add(self.user, 'income', '500')
        add(self.user, 'expense', '800')
        self.assertIn('So far this month, you spent ৳300.00 more than came in.', self.summary().insights)


class QueryCountTests(SummaryTestCase):
    def test_summary_uses_four_queries_however_much_data(self):
        budget(self.user, '5000')
        for i in range(30):
            add(self.user, 'expense', '10', category=['food', 'transport', 'bills'][i % 3])
        with self.assertNumQueries(4):
            services.get_dashboard_summary(self.user, today=TODAY)


class ZeroAndEvenEdgeCaseTests(SummaryTestCase):
    def test_percent_of_zero_total_is_zero_not_an_error(self):
        self.assertEqual(services.percent(D('0'), D('0')), D('0.0'))
        self.assertEqual(services.percent(D('50'), D('0')), D('0.0'))

    def test_exactly_even_month(self):
        add(self.user, 'income', '1200')
        add(self.user, 'expense', '1200')
        self.assertIn('So far this month, income and spending are exactly even.', self.summary().insights)
