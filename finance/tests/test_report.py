import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import services
from finance.models import GoalContribution, SavingsGoal, Transaction

User = get_user_model()
D = Decimal
TODAY = datetime.date(2026, 10, 20)   # October is the month in progress


def add(user, kind, amount, date, category=None):
    category = category or ('pocket_money' if kind == 'income' else 'food')
    return Transaction.objects.create(
        user=user, kind=kind, amount=D(amount), category=category,
        payment_method='' if kind == 'income' else 'cash', date=date,
    )


def contribute(user, amount, date, name='Phone'):
    goal, _ = SavingsGoal.objects.get_or_create(user=user, name=name, defaults={'target_amount': D('20000')})
    return GoalContribution.objects.create(goal=goal, amount=D(amount), date=date)


class ReportTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def report(self, year=2026, month=9):
        month_report = services.get_month_report(self.user, year, month, TODAY)
        return services.get_spending_report(self.user, month_report)

    def texts(self, insights):
        return [i.text for i in insights]


class ChangePercentTests(TestCase):
    def test_values(self):
        self.assertEqual(services.change_percent(D('115'), D('100')), D('15'))
        self.assertEqual(services.change_percent(D('85'), D('100')), D('-15'))
        self.assertEqual(services.change_percent(D('100'), D('300')), D('-67'))   # rounds half up
        self.assertIsNone(services.change_percent(D('100'), D('0')))           # no division by zero


class SpendingInsightTests(ReportTestCase):
    def test_spent_more_than_last_month(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '1150', datetime.date(2026, 9, 5))
        r = self.report()
        self.assertEqual(r.spending[0].text, 'You spent 15% more in September than in August (৳1,150.00 vs ৳1,000.00).')
        self.assertEqual(r.spending[0].tone, 'up')

    def test_expenses_decreased(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '800', datetime.date(2026, 9, 5))
        r = self.report()
        self.assertEqual(r.spending[0].text,
                         'Your recorded expenses decreased by 20% compared with August (৳800.00 vs ৳1,000.00).')
        self.assertEqual(r.spending[0].tone, 'down')

    def test_tiny_change_is_about_the_same(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '1004', datetime.date(2026, 9, 5))   # +0.4%
        self.assertIn('about the same as in August, slightly higher', self.report().spending[0].text)

    def test_exactly_equal(self):
        add(self.user, 'expense', '500', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '500', datetime.date(2026, 9, 5))
        self.assertEqual(self.report().spending[0].text, 'You spent exactly the same in September as in August (৳500.00).')

    def test_no_expenses_last_month_means_no_percentage(self):
        add(self.user, 'expense', '500', datetime.date(2026, 9, 5))
        r = self.report()
        self.assertEqual(r.spending[0].text,
                         'No expenses were recorded in August, so there is nothing to compare September with.')
        self.assertNotIn('%', r.spending[0].text)

    def test_no_expenses_this_month(self):
        add(self.user, 'income', '5000', datetime.date(2026, 9, 1))
        self.assertEqual(self.texts(self.report().spending), ['No expenses were recorded in September.'])

    def test_current_month_says_so_far(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 9, 5))
        add(self.user, 'expense', '600', datetime.date(2026, 10, 5))
        text = self.report(2026, 10).spending[0].text
        self.assertEqual(text, 'So far in October, your recorded expenses are 40% lower than in September '
                               '(৳600.00 vs ৳1,000.00). The month isn’t over yet.')

    def test_current_month_increase_says_so_far(self):
        add(self.user, 'expense', '500', datetime.date(2026, 9, 5))
        add(self.user, 'expense', '600', datetime.date(2026, 10, 5))
        self.assertIn('You spent 20% more in October so far than in September', self.report(2026, 10).spending[0].text)

    def test_year_named_when_comparing_across_new_year(self):
        add(self.user, 'expense', '100', datetime.date(2025, 12, 5))
        add(self.user, 'expense', '200', datetime.date(2026, 1, 5))
        self.assertIn('than in December 2025', self.report(2026, 1).spending[0].text)

    def test_largest_category(self):
        add(self.user, 'expense', '600', datetime.date(2026, 9, 5), 'food')
        add(self.user, 'expense', '400', datetime.date(2026, 9, 6), 'transport')
        self.assertIn('Food was your largest spending category in September: ৳600.00 (60.0% of expenses).',
                      self.texts(self.report().spending))

    def test_tied_largest_categories(self):
        add(self.user, 'expense', '300', datetime.date(2026, 9, 5), 'food')
        add(self.user, 'expense', '300', datetime.date(2026, 9, 6), 'transport')
        self.assertIn('Food and Transport were tied as your largest spending categories in September, at ৳300.00 each.',
                      self.texts(self.report().spending))

    def test_other_users_data_ignored_in_comparison(self):
        add(self.other, 'expense', '9999', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '500', datetime.date(2026, 9, 5))
        self.assertIn('No expenses were recorded in August', self.report().spending[0].text)

    def test_contributions_never_counted_as_spending(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '1000', datetime.date(2026, 9, 5))
        contribute(self.user, '5000', datetime.date(2026, 9, 6))
        self.assertEqual(self.report().spending[0].text,
                         'You spent exactly the same in September as in August (৳1,000.00).')


class SavingsInsightTests(ReportTestCase):
    def test_contribution_with_rate_and_comparison(self):
        add(self.user, 'income', '8000', datetime.date(2026, 9, 1))
        contribute(self.user, '1000', datetime.date(2026, 8, 3))
        contribute(self.user, '1500', datetime.date(2026, 9, 3))
        r = self.report()
        self.assertEqual(self.texts(r.savings), [
            'You contributed ৳1,500.00 towards your savings goals in September, 18.8% of recorded income.',
            'That is ৳500.00 more than you contributed in August.',
        ])
        self.assertEqual(r.savings[0].tone, 'saving')

    def test_less_and_same_than_last_month(self):
        contribute(self.user, '1000', datetime.date(2026, 8, 3))
        contribute(self.user, '400', datetime.date(2026, 9, 3))
        self.assertIn('That is ৳600.00 less than you contributed in August.', self.texts(self.report().savings))

    def test_no_income_gives_no_rate(self):
        contribute(self.user, '400', datetime.date(2026, 9, 3))
        texts = self.texts(self.report().savings)
        self.assertEqual(texts[0], 'You contributed ৳400.00 towards your savings goals in September. '
                                   'There was no recorded income to compare it with.')
        self.assertEqual(texts[1], 'You made no goal contributions in August.')

    def test_stopped_contributing(self):
        contribute(self.user, '700', datetime.date(2026, 8, 3))
        self.assertEqual(self.texts(self.report().savings),
                         ['You made no goal contributions in September; in August you contributed ৳700.00.'])

    def test_no_savings_insights_without_contributions(self):
        add(self.user, 'expense', '100', datetime.date(2026, 9, 5))
        self.assertEqual(self.report().savings, [])

    def test_empty_month_has_empty_report_parts(self):
        r = self.report()
        self.assertEqual(self.texts(r.spending), ['No expenses were recorded in September.'])
        self.assertEqual(r.savings, [])

    def test_report_queries(self):
        month_report = services.get_month_report(self.user, 2026, 9, TODAY)
        with self.assertNumQueries(2):   # last month's expenses and contributions
            services.get_spending_report(self.user, month_report)


class ReportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)

    def test_report_shown_with_separate_groups(self):
        today = timezone.localdate()
        add(self.user, 'expense', '500', today)
        contribute(self.user, '200', today)
        response = self.client.get(reverse('finance:stats'))
        self.assertContains(response, 'id="report-title"')
        self.assertContains(response, '<h3 class="report-heading">Spending</h3>')
        self.assertContains(response, '<h3 class="report-heading">Savings goals</h3>')
        self.assertContains(response, 'towards your savings goals')

    def test_empty_month_shows_no_report(self):
        response = self.client.get(reverse('finance:stats'))
        self.assertNotContains(response, 'id="report-title"')


class RemainingWordingTests(ReportTestCase):
    def test_tiny_decrease_is_about_the_same(self):
        add(self.user, 'expense', '1000', datetime.date(2026, 8, 5))
        add(self.user, 'expense', '996', datetime.date(2026, 9, 5))    # -0.4%
        self.assertIn('about the same as in August, slightly lower', self.report().spending[0].text)

    def test_same_contribution_as_last_month(self):
        contribute(self.user, '300', datetime.date(2026, 8, 3))
        contribute(self.user, '300', datetime.date(2026, 9, 3))
        self.assertIn('That is the same amount you contributed in August.', self.texts(self.report().savings))

    def test_three_way_category_tie(self):
        for category in ['food', 'transport', 'bills']:
            add(self.user, 'expense', '100', datetime.date(2026, 9, 5), category)
        self.assertIn('Bills, Food and Transport were tied as your largest spending categories in September, '
                      'at ৳100.00 each.', self.texts(self.report().spending))
