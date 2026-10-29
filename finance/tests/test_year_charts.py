import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import charts, services
from finance.models import GoalContribution, MonthlyBudget, SavingsGoal, Transaction

User = get_user_model()
D = Decimal
TODAY = datetime.date(2026, 10, 20)


def spend(user, amount, date, category='food'):
    return Transaction.objects.create(user=user, kind='expense', amount=D(amount), category=category,
                                      payment_method='cash', date=date)


class CategoryByMonthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def data(self, year=2026):
        return services.get_category_by_month(self.user, year, TODAY)

    def test_groups_by_month_and_category(self):
        spend(self.user, '100', datetime.date(2026, 3, 1), 'food')
        spend(self.user, '50', datetime.date(2026, 3, 31), 'food')
        spend(self.user, '80', datetime.date(2026, 3, 15), 'transport')
        spend(self.user, '40', datetime.date(2026, 4, 1), 'food')
        d = self.data()
        self.assertEqual(d.by_month[datetime.date(2026, 3, 1)], {'food': D('150.00'), 'transport': D('80.00')})
        self.assertEqual(d.by_month[datetime.date(2026, 4, 1)], {'food': D('40.00')})

    def test_year_totals_biggest_first_with_percent(self):
        spend(self.user, '300', datetime.date(2026, 1, 5), 'food')
        spend(self.user, '100', datetime.date(2026, 2, 5), 'bills')
        d = self.data()
        self.assertEqual([(s.category, s.total, s.percent) for s in d.totals],
                         [('food', D('300.00'), D('75.0')), ('bills', D('100.00'), D('25.0'))])

    def test_ties_use_the_fixed_category_order(self):
        spend(self.user, '100', datetime.date(2026, 1, 5), 'bills')
        spend(self.user, '100', datetime.date(2026, 1, 6), 'food')
        self.assertEqual([s.category for s in self.data().totals], ['food', 'bills'])

    def test_only_this_users_expenses_in_this_year(self):
        spend(self.other, '999', datetime.date(2026, 5, 5))
        spend(self.user, '999', datetime.date(2025, 12, 31))
        Transaction.objects.create(user=self.user, kind='income', amount=D('5000'), category='tuition',
                                   date=datetime.date(2026, 5, 1))
        goal = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))
        GoalContribution.objects.create(goal=goal, amount=D('300'), date=datetime.date(2026, 5, 2))
        d = self.data()
        self.assertFalse(d.has_data)
        self.assertEqual(d.by_month, {})

    def test_one_query(self):
        for month in range(1, 11):
            spend(self.user, '10', datetime.date(2026, month, 2), 'food')
            spend(self.user, '10', datetime.date(2026, month, 3), 'bills')
        with self.assertNumQueries(1):
            self.data()

    def test_fixed_order_lists_every_expense_category_once(self):
        self.assertEqual(
            [c.value for c in services.EXPENSE_CATEGORY_ORDER],
            ['food', 'transport', 'shopping', 'education', 'entertainment', 'bills', 'health', 'other_expense'],
        )


def month(n, expenses='0', limit=None, future=False):
    return services.MonthStat(month=datetime.date(2026, n, 1), income=D('0'), expenses=D(expenses),
                              budget_limit=D(limit) if limit else None, is_future=future)


class StackedChartTests(TestCase):
    def test_segments_stack_bottom_up_in_fixed_order(self):
        months = [month(1, '1000'), month(2, '0'), month(3, future=True)]
        by_month = {datetime.date(2026, 1, 1): {'transport': D('250'), 'food': D('750')}}
        chart = charts.stacked_category_chart(months, by_month, services.EXPENSE_CATEGORY_ORDER)
        jan = chart['groups'][0]
        self.assertEqual([s['category'] for s in jan['segments']], ['food', 'transport'])
        food, transport = jan['segments']
        self.assertAlmostEqual(food['y'] + food['h'] + 2, chart['baseline'])     # food sits on the baseline
        self.assertLess(transport['y'], food['y'])                               # transport above it
        self.assertEqual(food['title'], 'January 2026: Food ৳750.00')
        self.assertEqual(chart['groups'][1]['segments'], [])
        self.assertTrue(chart['groups'][2]['is_future'])
        self.assertEqual(chart['grid'][-1]['label'], '৳1,000')


class BudgetChartTests(TestCase):
    def test_within_over_no_budget_and_future(self):
        chart = charts.budget_chart([
            month(1, '800', limit='1000'),     # within
            month(2, '1500', limit='1000'),    # over by 500
            month(3, '600'),                    # no budget
            month(4, future=True),
        ])
        jan, feb, mar, apr = chart['groups']
        self.assertIsNotNone(jan['budget'])
        self.assertIsNone(jan['over'])
        self.assertEqual(feb['within']['title'], 'February 2026: spent ৳1,500.00, over budget by ৳500.00')
        self.assertIsNotNone(feb['over'])
        self.assertAlmostEqual(feb['within']['h'], feb['budget']['h'])          # green part stops at the limit
        self.assertTrue(mar['no_budget'])
        self.assertIsNone(mar['budget'])
        self.assertEqual(mar['within']['title'], 'March 2026: spent ৳600.00, no budget set')
        self.assertIsNone(apr['within'])
        self.assertEqual(chart['grid'][-1]['label'], '৳2,000')                   # 1,500 rounds up to 2,000


class YearViewChartsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def get(self):
        return self.client.get(reverse('finance:stats'), {'view': 'year', 'year': self.today.year})

    def test_empty_states(self):
        Transaction.objects.create(user=self.user, kind='income', amount=D('100'), category='tuition', date=self.today)
        response = self.get()
        self.assertContains(response, f'No expenses recorded in {self.today.year} yet.')
        self.assertContains(response, f'No budgets set in {self.today.year}.')

    def test_charts_legend_and_category_list(self):
        spend(self.user, '600', self.today, 'food')
        spend(self.user, '200', self.today, 'transport')
        MonthlyBudget.objects.create(user=self.user, month=self.today, limit=D('500'))
        response = self.get()
        self.assertContains(response, 'class="cat-food"')
        self.assertContains(response, 'class="bar-over"')
        self.assertEqual([c.value for c in response.context['category_legend']], ['food', 'transport'])
        self.assertContains(response, '1 of 1 month with a budget went over.')
        self.assertContains(response, '৳600.00</span> <span class="muted small">· 75.0%')
