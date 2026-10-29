import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from finance import charts, services
from finance.models import MonthlyBudget, Transaction

User = get_user_model()
D = Decimal
TODAY = datetime.date(2026, 10, 20)


def add(user, kind, amount, date, category=None):
    category = category or ('pocket_money' if kind == 'income' else 'food')
    return Transaction.objects.create(
        user=user, kind=kind, amount=D(amount), category=category,
        payment_method='' if kind == 'income' else 'cash', date=date,
    )


class StatsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def stats(self, today=TODAY):
        return services.get_monthly_stats(self.user, today=today)

    def month(self, stats, year, month):
        return next(m for m in stats.months if m.month == datetime.date(year, month, 1))


class MonthRangeTests(StatsTestCase):
    def test_twelve_months_oldest_first_ending_this_month(self):
        months = [m.month for m in self.stats().months]
        self.assertEqual(len(months), 12)
        self.assertEqual(months[0], datetime.date(2025, 11, 1))
        self.assertEqual(months[-1], datetime.date(2026, 10, 1))
        self.assertTrue(self.stats().months[-1].is_current)

    def test_range_crosses_year_boundary(self):
        months = [m.month for m in self.stats(today=datetime.date(2027, 1, 5)).months]
        self.assertEqual((months[0], months[-1]), (datetime.date(2026, 2, 1), datetime.date(2027, 1, 1)))

    def test_add_months(self):
        self.assertEqual(services.add_months(datetime.date(2026, 11, 1), 3), datetime.date(2027, 2, 1))
        self.assertEqual(services.add_months(datetime.date(2026, 1, 1), -1), datetime.date(2025, 12, 1))

    def test_empty_months_are_zero_not_missing(self):
        s = self.stats()
        self.assertFalse(s.has_data)
        for m in s.months:
            self.assertEqual((m.income, m.expenses, m.verdict), (D('0.00'), D('0.00'), 'empty'))


class BucketingTests(StatsTestCase):
    def test_transactions_land_in_their_own_calendar_month(self):
        add(self.user, 'expense', '10', datetime.date(2026, 9, 30))
        add(self.user, 'expense', '20', datetime.date(2026, 10, 1))
        add(self.user, 'expense', '40', datetime.date(2026, 10, 20))
        s = self.stats()
        self.assertEqual(self.month(s, 2026, 9).expenses, D('10.00'))
        self.assertEqual(self.month(s, 2026, 10).expenses, D('60.00'))

    def test_older_than_twelve_months_excluded(self):
        add(self.user, 'income', '999', datetime.date(2025, 10, 31))   # 13th month back
        add(self.user, 'income', '100', datetime.date(2025, 11, 1))    # first month in range
        s = self.stats()
        self.assertEqual(s.total_income, D('100.00'))

    def test_other_users_ignored(self):
        add(self.other, 'income', '5000', datetime.date(2026, 10, 2))
        MonthlyBudget.objects.create(user=self.other, month=datetime.date(2026, 10, 1), limit=D('10'))
        s = self.stats()
        self.assertFalse(s.has_data)
        self.assertEqual(s.budgeted_months, 0)

    def test_decimal_precision_in_monthly_sums(self):
        for _ in range(10):
            add(self.user, 'expense', '0.10', datetime.date(2026, 10, 3))
        self.assertEqual(self.month(self.stats(), 2026, 10).expenses, D('1.00'))


class VerdictTests(StatsTestCase):
    def test_saved_overspent_even(self):
        add(self.user, 'income', '1000', datetime.date(2026, 8, 1))
        add(self.user, 'expense', '400', datetime.date(2026, 8, 2))        # saved 600
        add(self.user, 'income', '300', datetime.date(2026, 9, 1))
        add(self.user, 'expense', '450.50', datetime.date(2026, 9, 2))     # overspent 150.50
        add(self.user, 'income', '200', datetime.date(2026, 10, 1))
        add(self.user, 'expense', '200', datetime.date(2026, 10, 2))       # even
        s = self.stats()
        aug, sep, oct_ = self.month(s, 2026, 8), self.month(s, 2026, 9), self.month(s, 2026, 10)
        self.assertEqual((aug.verdict, aug.net), ('saved', D('600.00')))
        self.assertEqual((sep.verdict, sep.net, sep.shortfall), ('overspent', D('-150.50'), D('150.50')))
        self.assertEqual((oct_.verdict, oct_.net), ('even', D('0.00')))
        self.assertEqual((s.saved_months, s.overspent_months), (1, 1))
        self.assertEqual(s.best_month, aug)
        self.assertEqual(s.worst_month, sep)
        self.assertEqual(s.total_net, D('449.50'))

    def test_spending_with_no_income_is_overspent(self):
        add(self.user, 'expense', '50', datetime.date(2026, 10, 2))
        self.assertEqual(self.month(self.stats(), 2026, 10).verdict, 'overspent')


class BudgetFlagTests(StatsTestCase):
    def test_over_budget_is_separate_from_saving(self):
        # Saved money overall, but still went over the budget.
        add(self.user, 'income', '10000', datetime.date(2026, 10, 1))
        add(self.user, 'expense', '3000', datetime.date(2026, 10, 2))
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=D('2500'))
        oct_ = self.month(self.stats(), 2026, 10)
        self.assertEqual(oct_.verdict, 'saved')
        self.assertTrue(oct_.over_budget)

    def test_spending_exactly_the_limit_is_not_over(self):
        add(self.user, 'expense', '2500', datetime.date(2026, 10, 2))
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=D('2500'))
        self.assertFalse(self.month(self.stats(), 2026, 10).over_budget)

    def test_no_budget_means_no_budget_verdict(self):
        add(self.user, 'expense', '99999', datetime.date(2026, 10, 2))
        oct_ = self.month(self.stats(), 2026, 10)
        self.assertIsNone(oct_.budget_limit)
        self.assertFalse(oct_.over_budget)

    def test_counts(self):
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 9, 1), limit=D('100'))
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=D('100'))
        add(self.user, 'expense', '150', datetime.date(2026, 9, 5))
        add(self.user, 'expense', '50', datetime.date(2026, 10, 5))
        s = self.stats()
        self.assertEqual((s.budgeted_months, s.over_budget_months), (2, 1))


class QueryCountTests(StatsTestCase):
    def test_two_queries_whatever_the_data_size(self):
        for month in range(1, 11):
            add(self.user, 'income', '100', datetime.date(2026, month, 3))
            add(self.user, 'expense', '60', datetime.date(2026, month, 4))
            MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, month, 1), limit=D('80'))
        with self.assertNumQueries(2):
            services.get_monthly_stats(self.user, today=TODAY)


class ChartGeometryTests(StatsTestCase):
    def test_tallest_bar_fills_plot_and_zero_has_no_height(self):
        add(self.user, 'income', '1000', datetime.date(2026, 10, 1))   # nice ceiling = 1000
        chart = charts.bar_chart(self.stats())
        oct_ = chart['groups'][-1]
        self.assertAlmostEqual(oct_['income']['h'], charts.PLOT_HEIGHT)
        self.assertEqual(oct_['expense']['h'], 0)
        self.assertEqual(chart['grid'][-1]['label'], '৳1,000')

    def test_nice_ceiling(self):
        cases = {'0': '1000', '7': '10', '180': '200', '2100': '2500', '4300': '5000', '123456': '200000'}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(charts.nice_ceiling(D(value)), D(expected))

    def test_hover_title_states_real_figures(self):
        add(self.user, 'income', '500', datetime.date(2026, 10, 1))
        add(self.user, 'expense', '800', datetime.date(2026, 10, 2))
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=D('600'))
        title = charts.bar_chart(self.stats())['groups'][-1]['title']
        self.assertEqual(title, 'October 2026: income ৳500.00, spent ৳800.00, '
                                'spent ৳300.00 more than came in, over the ৳600.00 budget')


class StatsViewTests(TestCase):
    url = reverse('finance:stats')

    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}")

    def test_empty_state(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'No transactions in the last 12 months yet')
        self.assertNotContains(response, '<svg class="bar-chart"')

    def test_renders_chart_and_table_with_real_figures(self):
        from django.utils import timezone
        today = timezone.localdate()
        add(self.user, 'income', '5000', today)
        add(self.user, 'expense', '1250.50', today)
        response = self.client.get(self.url)
        self.assertContains(response, '<svg class="bar-chart"')
        self.assertContains(response, '<table class="stats-table">')
        self.assertContains(response, '৳3,749.50')     # net, in the summary and the table
        self.assertContains(response, 'So far')        # current month marked
        self.assertEqual(len(response.context['months_newest_first']), 12)
        self.assertEqual(response.context['months_newest_first'][0].month, today.replace(day=1))

    def test_stats_tab_in_navigation(self):
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, f'href="{self.url}"')
