import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import services
from finance.forms import GoalContributionForm
from finance.models import GoalContribution, SavingsGoal, Transaction

User = get_user_model()
D = Decimal
TODAY = datetime.date(2026, 10, 20)
ADDED, TAKEN = GoalContribution.Kind.DEPOSIT, GoalContribution.Kind.WITHDRAWAL


def entry(g, amount, kind=ADDED, date=TODAY):
    return GoalContribution.objects.create(goal=g, amount=D(amount), kind=kind, date=date)


def income(user, amount, date=TODAY):
    return Transaction.objects.create(user=user, kind='income', amount=D(amount), category='tuition', date=date)


class NetTotalsTests(TestCase):
    """Every goal total is added minus taken out."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.goal = SavingsGoal.objects.create(user=cls.user, name='Phone', target_amount=D('1000'))
        entry(cls.goal, '800', ADDED, datetime.date(2026, 9, 10))
        entry(cls.goal, '300', TAKEN, datetime.date(2026, 10, 5))
        entry(cls.goal, '100', ADDED, datetime.date(2026, 10, 6))

    def test_goal_progress_and_balance(self):
        self.assertEqual(services.goal_progress(self.goal, TODAY).contributed, D('600.00'))
        self.assertEqual(services.goal_balance(self.goal), D('600.00'))

    def test_goal_list(self):
        active, _ = services.goals_with_progress(self.user, TODAY)
        self.assertEqual(active[0].contributed, D('600.00'))

    def test_period_and_lifetime_totals(self):
        self.assertEqual(services.total_set_aside(self.user), D('600.00'))
        self.assertEqual(services.contributions_between(self.user, datetime.date(2026, 10, 1), TODAY), D('-200.00'))
        by_month = services.contributions_by_month(self.user, datetime.date(2026, 1, 1), TODAY)
        self.assertEqual(by_month[datetime.date(2026, 9, 1)], D('800.00'))
        self.assertEqual(by_month[datetime.date(2026, 10, 1)], D('-200.00'))

    def test_savings_rate_never_negative(self):
        self.assertEqual(services.savings_rate(D('-200'), D('1000')), D('0.0'))


class WithdrawalFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        income(cls.user, '10000')
        cls.goal = SavingsGoal.objects.create(user=cls.user, name='Phone', target_amount=D('1000'))
        cls.deposit = entry(cls.goal, '500')

    def form(self, data, instance=None):
        return GoalContributionForm({'date': TODAY, **data}, goal=self.goal, instance=instance)

    def test_take_out_up_to_the_balance(self):
        self.assertTrue(self.form({'kind': TAKEN, 'amount': '500'}).is_valid())

    def test_cannot_take_out_more_than_the_balance(self):
        form = self.form({'kind': TAKEN, 'amount': '500.01'})
        self.assertFalse(form.is_valid())
        self.assertIn('at most ৳500.00', form.errors['amount'][0])

    def test_missing_kind_means_added(self):
        form = self.form({'amount': '50'})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.save().kind, ADDED)

    def test_editing_a_withdrawal_ignores_its_old_amount(self):
        out = entry(self.goal, '400', TAKEN)
        self.assertTrue(self.form({'kind': TAKEN, 'amount': '500'}, instance=out).is_valid())
        self.assertFalse(self.form({'kind': TAKEN, 'amount': '501'}, instance=out).is_valid())

    def test_shrinking_a_deposit_below_what_was_taken_out_is_refused(self):
        entry(self.goal, '400', TAKEN)
        form = self.form({'kind': ADDED, 'amount': '300'}, instance=self.deposit)
        self.assertFalse(form.is_valid())
        self.assertIn('needs at least ৳400.00', form.errors['amount'][0])

    def test_unknown_kind_rejected(self):
        self.assertFalse(self.form({'kind': 'gift', 'amount': '10'}).is_valid())

    def test_database_rejects_unknown_kind(self):
        with self.assertRaises(IntegrityError):
            entry(self.goal, '10', 'gift')


class WithdrawalViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.goal = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))

    def test_take_out_through_the_goal_page(self):
        entry(self.goal, '500', date=self.today)
        response = self.client.post(reverse('finance:contribution_create', args=[self.goal.pk]),
                                    {'kind': TAKEN, 'amount': '200', 'date': self.today}, follow=True)
        self.assertContains(response, '৳200.00 taken out of “Phone”.')
        self.assertContains(response, '−৳200.00')
        self.assertEqual(services.goal_balance(self.goal), D('300.00'))

    def test_card_take_out_button_preselects_it(self):
        detail = reverse('finance:goal_detail', args=[self.goal.pk])
        self.assertNotContains(self.client.get(reverse('finance:goal_list')), '− Take out')   # nothing to take out yet
        entry(self.goal, '500', date=self.today)
        self.assertContains(self.client.get(reverse('finance:goal_list')), f'href="{detail}?kind=withdrawal#add"')
        self.assertEqual(self.client.get(detail, {'kind': 'withdrawal'}).context['form']['kind'].value(), 'withdrawal')
        self.assertEqual(self.client.get(detail, {'kind': 'junk'}).context['form']['kind'].value(), 'deposit')

    def test_delete_blocked_when_money_was_taken_out(self):
        deposit = entry(self.goal, '500', date=self.today)
        entry(self.goal, '300', TAKEN, date=self.today)
        url = reverse('finance:contribution_delete', args=[deposit.pk])
        self.assertContains(self.client.get(url), 'would go ৳300.00 below ৳0')
        self.client.post(url)
        self.assertTrue(GoalContribution.objects.filter(pk=deposit.pk).exists())

    def test_deleting_a_withdrawal_puts_money_back(self):
        income(self.user, '1000', self.today)
        entry(self.goal, '500', date=self.today)
        out = entry(self.goal, '300', TAKEN, date=self.today)
        self.client.post(reverse('finance:contribution_delete', args=[out.pk]))
        self.assertEqual(services.goal_balance(self.goal), D('500.00'))

    def test_day_page_shows_net_goal_money(self):
        entry(self.goal, '500', date=self.today)
        entry(self.goal, '200', TAKEN, date=self.today)
        response = self.client.get(reverse('finance:day_detail', args=[self.today.isoformat()]))
        self.assertEqual(response.context['to_goals'], D('300.00'))
        self.assertContains(response, '−৳200.00')

    def test_report_describes_a_month_with_more_taken_out(self):
        entry(self.goal, '300', TAKEN, date=self.today)     # money added in an earlier month isn't needed here
        response = self.client.get(reverse('finance:stats'), {'view': 'month'})
        self.assertContains(response, 'You took ৳300.00 more out of your savings goals than you put in')

    def test_cannot_take_out_of_another_users_goal(self):
        other = User.objects.create_user('other', password='x')
        theirs = SavingsGoal.objects.create(user=other, name='Bike', target_amount=D('1000'))
        entry(theirs, '500', date=self.today)
        response = self.client.post(reverse('finance:contribution_create', args=[theirs.pk]),
                                    {'kind': TAKEN, 'amount': '100', 'date': self.today})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(services.goal_balance(theirs), D('500.00'))
