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


def spend(user, amount, date):
    return Transaction.objects.create(user=user, kind='expense', amount=D(amount), category='food',
                                      payment_method='cash', date=date)


class DailyAllowanceTests(TestCase):
    def status(self, limit, spent, today):
        return services.get_budget_status(MonthlyBudget(limit=D(limit)), D(spent), today)

    def test_remaining_divided_by_days_left_rounded_down(self):
        b = self.status('1000', '0.01', datetime.date(2026, 10, 20))   # 999.99 over 12 days
        self.assertEqual(b.daily_allowance, D('83.33'))

    def test_last_day_gets_everything_left(self):
        self.assertEqual(self.status('1000', '400', datetime.date(2026, 10, 31)).daily_allowance, D('600.00'))

    def test_zero_when_used_up_or_over(self):
        self.assertEqual(self.status('1000', '1000', datetime.date(2026, 10, 20)).daily_allowance, D('0.00'))
        self.assertEqual(self.status('1000', '1500', datetime.date(2026, 10, 20)).daily_allowance, D('0.00'))


class SpendingPaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def pace(self, limit=None, today=datetime.date(2026, 10, 10)):
        return services.get_spending_pace(self.user, D(limit) if limit else None, today)

    def test_running_totals_by_transaction_date(self):
        spend(self.user, '100', datetime.date(2026, 10, 1))
        spend(self.user, '50', datetime.date(2026, 10, 1))
        spend(self.user, '200', datetime.date(2026, 10, 4))
        spend(self.user, '999', datetime.date(2026, 9, 30))        # last month
        spend(self.other, '777', datetime.date(2026, 10, 2))       # someone else
        p = self.pace()
        self.assertEqual(len(p.current), 10)
        self.assertEqual(p.current[:4], [D('150.00'), D('150.00'), D('150.00'), D('350.00')])
        self.assertEqual(p.spent, D('350.00'))
        self.assertEqual((len(p.previous), p.previous[-1]), (30, D('999.00')))

    def test_income_and_goal_contributions_are_not_spending(self):
        Transaction.objects.create(user=self.user, kind='income', amount=D('5000'), category='tuition',
                                   date=datetime.date(2026, 10, 2))
        goal = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))
        GoalContribution.objects.create(goal=goal, amount=D('300'), date=datetime.date(2026, 10, 3))
        self.assertEqual(self.pace().spent, D('0.00'))
        self.assertFalse(self.pace().has_data)

    def test_status_against_even_budget_pace(self):
        # Even pace on 10 Oct with a ৳3,100 budget: 3100 x 10 / 31 = ৳1,000.
        spend(self.user, '1000', datetime.date(2026, 10, 3))
        p = self.pace('3100')
        self.assertEqual((p.even_pace_today, p.status), (D('1000.00'), 'within'))   # equal is within
        spend(self.user, '0.01', datetime.date(2026, 10, 9))
        self.assertEqual(self.pace('3100').status, 'faster')

    def test_no_budget_means_no_status(self):
        spend(self.user, '500', datetime.date(2026, 10, 3))
        p = self.pace()
        self.assertIsNone(p.status)
        self.assertIsNone(p.even_pace_today)

    def test_previous_same_day_capped_at_short_month(self):
        spend(self.user, '280', datetime.date(2026, 2, 28))
        p = self.pace(today=datetime.date(2026, 3, 31))          # February has 28 days
        self.assertEqual(p.previous_same_day, D('280.00'))
        self.assertEqual(p.days_in_month, 31)

    def test_january_compares_with_december(self):
        spend(self.user, '400', datetime.date(2025, 12, 5))
        p = self.pace(today=datetime.date(2026, 1, 5))
        self.assertEqual(p.previous_same_day, D('400.00'))

    def test_two_queries(self):
        for day in range(1, 11):
            spend(self.user, '10', datetime.date(2026, 10, day))
            spend(self.user, '10', datetime.date(2026, 9, day))
        with self.assertNumQueries(2):
            self.pace('3000')


class PaceChartTests(TestCase):
    def test_geometry(self):
        pace = services.SpendingPace(
            today=datetime.date(2026, 10, 2), days_in_month=31,
            current=[D('100'), D('1000')], previous=[D('0')] * 30, budget_limit=D('2000'),
        )
        chart = charts.pace_chart(pace)
        first = chart['current'].split()[0]
        self.assertEqual(first, f"{charts.PACE_LEFT:.1f},{chart['baseline']:.1f}")   # starts at ৳0 on day 0
        self.assertEqual(chart['grid'][-1]['label'], '৳2,000')                        # budget sets the top
        self.assertEqual(chart['previous'], '')                                        # nothing spent last month
        self.assertAlmostEqual(chart['budget']['x2'], chart['right_edge'])
        self.assertEqual([d['label'] for d in chart['days']], [1, 10, 20, 31])


class DashboardRefocusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def test_no_budget_invites_setting_one(self):
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, 'Set a monthly budget to see how much you can spend each day.')
        self.assertContains(response, 'will appear here as you add expenses')

    def test_allowance_and_pace_with_budget(self):
        MonthlyBudget.objects.create(user=self.user, month=self.today, limit=D('3000'))
        spend(self.user, '100', self.today)
        response = self.client.get(reverse('finance:dashboard'))
        summary = response.context['summary']
        self.assertContains(response, services.taka(summary.budget.daily_allowance))
        self.assertContains(response, 'class="pace-current"')
        self.assertContains(response, 'Spending pace')

    def test_over_budget_shows_zero_allowance(self):
        MonthlyBudget.objects.create(user=self.user, month=self.today, limit=D('100'))
        spend(self.user, '250', self.today)
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, 'You’re ৳150.00 over this month’s budget.')

    def test_categories_and_insights_moved_to_stats(self):
        spend(self.user, '100', self.today)
        response = self.client.get(reverse('finance:dashboard'))
        self.assertNotContains(response, 'id="categories-title"')
        self.assertNotContains(response, 'What we noticed')
        self.assertContains(response, f'href="{reverse("finance:stats")}"')

    def test_goals_card_shows_active_goals_only(self):
        active = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))
        done = SavingsGoal.objects.create(user=self.user, name='Bag', target_amount=D('10'))
        GoalContribution.objects.create(goal=done, amount=D('10'), date=self.today)
        response = self.client.get(reverse('finance:dashboard'))
        self.assertEqual([p.goal for p in response.context['goals']], [active])


class NoComparisonTests(TestCase):
    def test_no_spending_last_month_means_no_comparison(self):
        user = User.objects.create_user('mitu', password='x')
        spend(user, '100', datetime.date(2026, 10, 3))
        p = services.get_spending_pace(user, None, datetime.date(2026, 10, 10))
        self.assertIsNone(p.previous_same_day)
