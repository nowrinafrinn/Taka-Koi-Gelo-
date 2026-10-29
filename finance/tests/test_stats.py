import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import charts, services
from finance.forms import StatsPeriodForm
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


def stat(income='0', expenses='0', **kwargs):
    fields = {'month': datetime.date(2026, 5, 1), 'income': D(income), 'expenses': D(expenses), 'budget_limit': None}
    fields.update(kwargs)
    return services.MonthStat(**fields)


class MonthStatRulesTests(TestCase):
    def test_surplus_is_income_minus_expenses(self):
        s = stat('1000', '400')
        self.assertEqual((s.verdict, s.net), ('surplus', D('600')))

    def test_deficit_only_when_expenses_exceed_income(self):
        s = stat('300', '450.50')
        self.assertEqual((s.verdict, s.shortfall), ('deficit', D('150.50')))

    def test_high_spending_alone_is_not_a_deficit(self):
        self.assertEqual(stat('90000', '80000').verdict, 'surplus')

    def test_no_income_gives_no_surplus_or_deficit_verdict(self):
        s = stat('0', '500')
        self.assertEqual(s.verdict, 'no_income')

    def test_even_empty_future(self):
        self.assertEqual(stat('200', '200').verdict, 'even')
        self.assertEqual(stat().verdict, 'empty')
        self.assertEqual(stat('100', '0', is_future=True).verdict, 'future')

    def test_budget_helpers(self):
        over = stat('0', '700', budget_limit=D('500'))
        within = stat('0', '300', budget_limit=D('500'))
        self.assertEqual((over.over_budget, over.budget_over_by, over.budget_left), (True, D('200'), D('0.00')))
        self.assertEqual((within.over_budget, within.budget_over_by, within.budget_left), (False, D('0.00'), D('200')))
        self.assertFalse(stat('0', '500', budget_limit=D('500')).over_budget)   # equal is not over

    def test_add_months(self):
        self.assertEqual(services.add_months(datetime.date(2026, 11, 1), 3), datetime.date(2027, 2, 1))
        self.assertEqual(services.add_months(datetime.date(2026, 1, 1), -1), datetime.date(2025, 12, 1))


class YearComparisonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def year(self, year=2026, today=TODAY):
        return services.get_year_comparison(self.user, year, today)

    def test_always_january_to_december_with_future_months_flagged(self):
        c = self.year()
        self.assertEqual([m.month.month for m in c.months], list(range(1, 13)))
        self.assertEqual([m.month.month for m in c.months if m.is_future], [11, 12])
        self.assertTrue(c.months[9].is_current)
        self.assertEqual(c.months_in_period, 10)

    def test_past_year_has_twelve_months_in_period(self):
        self.assertEqual(self.year(2025).months_in_period, 12)

    def test_empty_year(self):
        c = self.year()
        self.assertFalse(c.has_data)
        self.assertEqual((c.total_income, c.total_expenses, c.average_expenses), (D('0.00'), D('0.00'), D('0.00')))
        self.assertIsNone(c.highest_spending)
        self.assertIsNone(c.highest_surplus)

    def test_transaction_date_decides_the_month_across_year_boundary(self):
        add(self.user, 'expense', '10', datetime.date(2025, 12, 31))
        add(self.user, 'expense', '20', datetime.date(2026, 1, 1))
        self.assertEqual(self.year(2025).months[11].expenses, D('10.00'))
        self.assertEqual(self.year(2026).months[0].expenses, D('20.00'))
        self.assertEqual(self.year(2026).total_expenses, D('20.00'))

    def test_totals_highlights_and_counts(self):
        add(self.user, 'income', '1000', datetime.date(2026, 2, 1))
        add(self.user, 'expense', '400', datetime.date(2026, 2, 2))      # surplus 600
        add(self.user, 'income', '300', datetime.date(2026, 3, 1))
        add(self.user, 'expense', '900', datetime.date(2026, 3, 2))      # deficit 600, highest spending
        add(self.user, 'expense', '50', datetime.date(2026, 4, 2))       # no income
        c = self.year()
        self.assertEqual((c.total_income, c.total_expenses, c.net), (D('1300.00'), D('1350.00'), D('-50.00')))
        self.assertEqual(c.shortfall, D('50.00'))
        self.assertEqual(c.highest_spending.month, datetime.date(2026, 3, 1))
        self.assertEqual(c.highest_surplus.month, datetime.date(2026, 2, 1))
        self.assertEqual((c.surplus_months, c.deficit_months, c.no_income_months), (1, 1, 1))

    def test_average_includes_months_with_nothing_recorded(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 1, 5))
        add(self.user, 'expense', '1000', datetime.date(2026, 10, 5))
        # ৳2,000 over the 10 months Jan..Oct, not over the 2 months with records.
        self.assertEqual(self.year().average_expenses, D('200.00'))

    def test_average_rounds_to_paisa(self):
        add(self.user, 'expense', '100', datetime.date(2026, 1, 5))
        self.assertEqual(self.year(today=datetime.date(2026, 3, 1)).average_expenses, D('33.33'))

    def test_highest_spending_tie_keeps_earliest_month(self):
        add(self.user, 'expense', '500', datetime.date(2026, 4, 5))
        add(self.user, 'expense', '500', datetime.date(2026, 6, 5))
        self.assertEqual(self.year().highest_spending.month, datetime.date(2026, 4, 1))

    def test_user_with_no_income_gets_no_surplus_or_deficit_claims(self):
        add(self.user, 'expense', '700', datetime.date(2026, 5, 5))
        add(self.user, 'expense', '300', datetime.date(2026, 6, 5))
        c = self.year()
        self.assertFalse(c.has_income)
        self.assertEqual(c.total_expenses, D('1000.00'))
        self.assertEqual((c.surplus_months, c.deficit_months, c.no_income_months), (0, 0, 2))
        self.assertIsNone(c.highest_surplus)

    def test_other_users_and_their_budgets_ignored(self):
        add(self.other, 'income', '5000', datetime.date(2026, 5, 5))
        MonthlyBudget.objects.create(user=self.other, month=datetime.date(2026, 5, 1), limit=D('10'))
        c = self.year()
        self.assertFalse(c.has_data)
        self.assertEqual(c.budgeted_months, 0)

    def test_budget_flags(self):
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 5, 1), limit=D('100'))
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 6, 1), limit=D('100'))
        add(self.user, 'expense', '150', datetime.date(2026, 5, 5))
        add(self.user, 'expense', '100', datetime.date(2026, 6, 5))
        c = self.year()
        self.assertEqual((c.budgeted_months, c.over_budget_months), (2, 1))

    def test_edits_and_deletes_are_reflected(self):
        t = add(self.user, 'expense', '100', datetime.date(2026, 5, 5))
        t.date = datetime.date(2026, 6, 5)
        t.save()
        c = self.year()
        self.assertEqual((c.months[4].expenses, c.months[5].expenses), (D('0.00'), D('100.00')))
        t.delete()
        self.assertEqual(self.year().total_expenses, D('0.00'))

    def test_three_queries_whatever_the_data_size(self):
        for month in range(1, 11):
            add(self.user, 'income', '100', datetime.date(2026, month, 3))
            add(self.user, 'expense', '60', datetime.date(2026, month, 4))
            MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, month, 1), limit=D('80'))
        with self.assertNumQueries(3):   # transactions, budgets, goal contributions
            self.year()


class MonthReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def report(self, year=2026, month=10):
        return services.get_month_report(self.user, year, month, TODAY)

    def test_month_totals_categories_and_count(self):
        add(self.user, 'income', '5000', datetime.date(2026, 10, 1))
        add(self.user, 'expense', '600', datetime.date(2026, 10, 2), 'food')
        add(self.user, 'expense', '150', datetime.date(2026, 10, 3), 'food')
        add(self.user, 'expense', '250', datetime.date(2026, 10, 31), 'transport')
        add(self.user, 'expense', '999', datetime.date(2026, 9, 30), 'shopping')      # other month
        add(self.other, 'expense', '999', datetime.date(2026, 10, 5), 'shopping')     # other user
        r = self.report()
        self.assertEqual((r.stat.income, r.stat.expenses, r.stat.verdict), (D('5000.00'), D('1000.00'), 'surplus'))
        self.assertEqual(r.transaction_count, 4)
        self.assertEqual([(c.category, c.total, c.percent) for c in r.categories],
                         [('food', D('750.00'), D('75.0')), ('transport', D('250.00'), D('25.0'))])
        self.assertEqual((r.start, r.end), (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)))

    def test_empty_month(self):
        r = self.report(2026, 2)
        self.assertEqual((r.stat.verdict, r.categories, r.transaction_count), ('empty', [], 0))
        self.assertEqual(r.end, datetime.date(2026, 2, 28))

    def test_month_with_only_income(self):
        add(self.user, 'income', '500', datetime.date(2026, 10, 1))
        r = self.report()
        self.assertEqual((r.stat.verdict, r.categories), ('surplus', []))

    def test_month_budget(self):
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=D('400'))
        add(self.user, 'expense', '500', datetime.date(2026, 10, 2))
        self.assertTrue(self.report().stat.over_budget)

    def test_four_queries(self):
        add(self.user, 'expense', '10', datetime.date(2026, 10, 2))
        with self.assertNumQueries(4):   # totals, categories, budget, goal contributions
            self.report()

    def test_first_transaction_year(self):
        self.assertEqual(services.first_transaction_year(self.user, TODAY), 2026)
        add(self.user, 'expense', '10', datetime.date(2024, 3, 2))
        self.assertEqual(services.first_transaction_year(self.user, TODAY), 2024)


class PeriodFormTests(TestCase):
    def period(self, data):
        return StatsPeriodForm(data or None, first_year=2024, today=TODAY).period()

    def test_defaults_to_current_month(self):
        self.assertEqual(self.period({}), ('month', 2026, 10))

    def test_valid_choices(self):
        self.assertEqual(self.period({'view': 'year', 'year': '2025'}), ('year', 2025, 12))
        self.assertEqual(self.period({'view': 'month', 'year': '2025', 'month': '3'}), ('month', 2025, 3))

    def test_invalid_input_falls_back_safely(self):
        for data in [{'month': '13'}, {'year': 'abc'}, {'year': '1999'}, {'view': 'decade'}, {'year': '2030'}]:
            with self.subTest(data=data):
                self.assertEqual(self.period(data), ('month', 2026, 10))

    def test_future_month_clamped_to_current(self):
        self.assertEqual(self.period({'year': '2026', 'month': '12'}), ('month', 2026, 10))


class ChartTests(TestCase):
    def test_titles_use_surplus_deficit_and_no_income_wording(self):
        months = [
            stat('1000', '400', month=datetime.date(2026, 1, 1)),
            stat('300', '450', month=datetime.date(2026, 2, 1), budget_limit=D('400')),
            stat('0', '50', month=datetime.date(2026, 3, 1)),
            stat(month=datetime.date(2026, 4, 1), is_future=True),
        ]
        titles = [g['title'] for g in charts.bar_chart(months)['groups']]
        self.assertEqual(titles, [
            'January 2026: income ৳1,000.00, expenses ৳400.00, surplus ৳600.00',
            'February 2026: income ৳300.00, expenses ৳450.00, deficit ৳150.00, over the ৳400.00 budget',
            'March 2026: income ৳0.00, expenses ৳50.00, no income recorded',
            'April 2026: not started yet',
        ])

    def test_tallest_bar_fills_plot(self):
        groups = charts.bar_chart([stat('1000', '0'), stat()])['groups']
        self.assertAlmostEqual(groups[0]['income']['h'], charts.PLOT_HEIGHT)
        self.assertEqual(groups[1]['income']['h'], 0)

    def test_nice_ceiling(self):
        cases = {'0': '1000', '7': '10', '180': '200', '2100': '2500', '4300': '5000', '123456': '200000'}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(charts.nice_ceiling(D(value)), D(expected))


class StatsViewTests(TestCase):
    url = reverse('finance:stats')

    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('accounts:login')}?next={self.url}")

    def test_month_view_is_default_and_handles_empty_month(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['view'], 'month')
        self.assertContains(response, 'Nothing recorded in')

    def test_month_view_figures_and_wording(self):
        add(self.user, 'income', '5000', self.today)
        add(self.user, 'expense', '1250.50', self.today)
        response = self.client.get(self.url)
        self.assertContains(response, 'Surplus ৳3,749.50')
        self.assertContains(response, 'not necessarily money saved')
        self.assertNotContains(response, 'Saved')
        self.assertIsNone(response.context['following'])       # no "next month" past the current one

    def test_no_income_month_makes_no_claim(self):
        add(self.user, 'expense', '300', self.today)
        response = self.client.get(self.url)
        self.assertContains(response, 'No income recorded')
        self.assertNotContains(response, 'Deficit')
        self.assertNotContains(response, 'Surplus ৳')

    def test_year_view_renders_chart_and_table(self):
        add(self.user, 'income', '5000', self.today)
        add(self.user, 'expense', '800', self.today)
        response = self.client.get(self.url, {'view': 'year', 'year': self.today.year})
        self.assertContains(response, '<svg class="bar-chart"')
        self.assertContains(response, '<table class="stats-table">')
        self.assertContains(response, 'Average monthly expenses')
        self.assertEqual(len(response.context['comparison'].months), 12)

    def test_bad_parameters_never_error(self):
        for params in [{'month': '13'}, {'year': 'abc'}, {'view': 'year', 'year': '1800'}, {'month': '-1'}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 200)

    def test_only_own_data_shown(self):
        other = User.objects.create_user('other', password='x')
        add(other, 'income', '77777', self.today)
        response = self.client.get(self.url, {'view': 'year', 'year': self.today.year})
        self.assertNotContains(response, '77,777')

    def test_stats_tab_in_navigation(self):
        self.assertContains(self.client.get(reverse('finance:dashboard')), f'href="{self.url}"')
