import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import services
from finance.forms import GoalContributionForm
from finance.models import GoalContribution, MonthlyBudget, SavingsGoal, Transaction

User = get_user_model()
D = Decimal
ADDED, TAKEN = GoalContribution.Kind.DEPOSIT, GoalContribution.Kind.WITHDRAWAL


def record(user, kind, amount, date=None):
    return Transaction.objects.create(user=user, kind=kind, amount=D(amount),
                                      category='tuition' if kind == 'income' else 'food',
                                      payment_method='' if kind == 'income' else 'cash',
                                      date=date or timezone.localdate())


def entry(g, amount, kind=ADDED):
    return GoalContribution.objects.create(goal=g, amount=D(amount), kind=kind, date=timezone.localdate())


class MoneySplitTests(TestCase):
    """Total balance = saved in goals + spendable."""

    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        record(self.user, 'income', '2050')
        record(self.user, 'expense', '1050')                        # total ৳1,000
        self.phone = SavingsGoal.objects.create(user=self.user, name='New Phone', target_amount=D('160000'))
        self.tour = SavingsGoal.objects.create(user=self.user, name='Tour', target_amount=D('10000'))

    def test_all_saved_leaves_nothing_spendable(self):
        entry(self.phone, '1000')
        split = services.get_money_split(self.user)
        self.assertEqual((split.total, split.saved, split.spendable, split.over_saved),
                         (D('1000.00'), D('1000.00'), D('0.00'), D('0.00')))
        self.assertEqual(split.goals, [(self.phone, D('1000.00'))])
        self.assertEqual(split.saved_percent, D('100.0'))

    def test_over_saved_is_reported_not_fixed(self):
        entry(self.phone, '1000')
        entry(self.tour, '1000')                                    # how the live account got here
        split = services.get_money_split(self.user)
        self.assertEqual(split.spendable, D('-1000.00'))
        self.assertEqual(split.over_saved, D('1000.00'))
        self.assertEqual(GoalContribution.objects.count(), 2)       # nothing deleted or changed

    def test_goals_without_money_are_not_listed(self):
        entry(self.phone, '300')
        entry(self.tour, '200')
        entry(self.tour, '200', TAKEN)
        self.assertEqual(services.get_money_split(self.user).goals, [(self.phone, D('300.00'))])


class AddingIsCappedAtSpendableTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        record(self.user, 'income', '1000')
        self.phone = SavingsGoal.objects.create(user=self.user, name='New Phone', target_amount=D('160000'))
        self.tour = SavingsGoal.objects.create(user=self.user, name='Tour', target_amount=D('10000'))

    def form(self, goal, data, instance=None):
        return GoalContributionForm({'date': timezone.localdate(), **data}, goal=goal, instance=instance)

    def test_can_add_up_to_spendable(self):
        self.assertTrue(self.form(self.phone, {'kind': ADDED, 'amount': '1000'}).is_valid())
        form = self.form(self.phone, {'kind': ADDED, 'amount': '1000.01'})
        self.assertFalse(form.is_valid())
        self.assertIn('You can add at most ৳1,000.00', form.errors['amount'][0])

    def test_users_scenario_second_goal_gets_nothing(self):
        entry(self.phone, '1000')
        form = self.form(self.tour, {'kind': ADDED, 'amount': '1'})
        self.assertFalse(form.is_valid())
        self.assertIn('You can add at most ৳0.00', form.errors['amount'][0])

    def test_taking_out_frees_money_for_another_goal(self):
        entry(self.phone, '1000')
        entry(self.phone, '400', TAKEN)
        self.assertTrue(self.form(self.tour, {'kind': ADDED, 'amount': '400'}).is_valid())

    def test_editing_an_entry_counts_its_own_amount_as_available(self):
        own = entry(self.phone, '600')
        self.assertTrue(self.form(self.phone, {'kind': ADDED, 'amount': '1000'}, instance=own).is_valid())
        self.assertFalse(self.form(self.phone, {'kind': ADDED, 'amount': '1001'}, instance=own).is_valid())

    def test_over_saved_account_can_still_lower_or_take_out(self):
        first = entry(self.phone, '1000')
        entry(self.tour, '1000')                                    # over-saved by ৳1,000
        self.assertTrue(self.form(self.phone, {'kind': ADDED, 'amount': '500'}, instance=first).is_valid())
        self.assertTrue(self.form(self.tour, {'kind': TAKEN, 'amount': '1000'}).is_valid())
        self.assertFalse(self.form(self.phone, {'kind': ADDED, 'amount': '1001'}, instance=first).is_valid())

    def test_withdrawals_are_not_limited_by_spendable(self):
        entry(self.phone, '1000')
        record(self.user, 'expense', '900')                         # spent into savings
        self.assertTrue(self.form(self.phone, {'kind': TAKEN, 'amount': '1000'}).is_valid())

    def test_expenses_are_never_blocked(self):
        entry(self.phone, '1000')
        self.client.force_login(self.user)
        self.client.post(reverse('finance:expense_create'), {
            'amount': '200', 'category': 'food', 'payment_method': 'cash',
            'date': timezone.localdate().isoformat(), 'note': '',
        })
        self.assertTrue(Transaction.objects.filter(kind='expense', amount=D('200')).exists())

    def test_deleting_a_withdrawal_blocked_when_money_was_spent(self):
        entry(self.phone, '1000')
        out = entry(self.phone, '500', TAKEN)
        record(self.user, 'expense', '500')                         # the ৳500 taken out was spent
        self.client.force_login(self.user)
        url = reverse('finance:contribution_delete', args=[out.pk])
        self.assertContains(self.client.get(url), 'hold ৳500.00 more than your balance')
        self.client.post(url)
        self.assertTrue(GoalContribution.objects.filter(pk=out.pk).exists())

    def test_goal_page_shows_how_much_can_be_added(self):
        self.client.force_login(self.user)
        detail = reverse('finance:goal_detail', args=[self.tour.pk])
        self.assertContains(self.client.get(detail), 'You can add up to <strong>৳1,000.00</strong>')
        entry(self.phone, '1000')
        self.assertContains(self.client.get(detail), 'You have <strong>৳0.00</strong> spendable')


class DashboardSplitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        record(self.user, 'income', '2050')
        record(self.user, 'expense', '1050')
        self.phone = SavingsGoal.objects.create(user=self.user, name='New Phone', target_amount=D('160000'))

    def test_card_shows_total_saved_and_spendable(self):
        entry(self.phone, '1000')
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, 'Total balance')
        self.assertContains(response, 'Saved in goals')
        self.assertContains(response, 'New Phone ৳1,000.00')
        self.assertContains(response, 'Spendable')
        self.assertNotContains(response, 'not set aside')

    def test_warning_when_goals_hold_more_than_the_balance(self):
        tour = SavingsGoal.objects.create(user=self.user, name='Tour', target_amount=D('10000'))
        entry(self.phone, '1000')
        entry(tour, '1000')
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, 'Your goals hold ৳1,000.00 more than your balance')
        self.assertContains(response, '-৳1,000.00')                  # spendable shown as negative

    def test_safe_to_spend_is_capped_by_spendable(self):
        MonthlyBudget.objects.create(user=self.user, month=timezone.localdate(), limit=D('5000'))
        entry(self.phone, '700')                                    # spendable ৳300, budget left ৳3,950
        response = self.client.get(reverse('finance:dashboard'))
        safe = response.context['safe']
        self.assertTrue(safe.limited_by_savings)
        self.assertEqual(safe.left, D('300.00'))
        self.assertContains(response, 'Only ৳300.00 is spendable outside your goals')

    def test_safe_to_spend_is_zero_when_over_saved(self):
        MonthlyBudget.objects.create(user=self.user, month=timezone.localdate(), limit=D('5000'))
        tour = SavingsGoal.objects.create(user=self.user, name='Tour', target_amount=D('10000'))
        entry(self.phone, '1000')
        entry(tour, '1000')
        self.assertEqual(self.client.get(reverse('finance:dashboard')).context['safe'].per_day, D('0.00'))


class SafeToSpendTests(TestCase):
    def test_budget_limits_when_plenty_is_spendable(self):
        budget = services.BudgetStatus(limit=D('3000'), spent=D('1000'), remaining=D('2000'),
                                       used_percent=D('33.3'), state='ok', days_left=10)
        safe = services.safe_to_spend(budget, D('9000'))
        self.assertEqual((safe.left, safe.per_day, safe.limited_by_savings), (D('2000'), D('200.00'), False))

    def test_no_budget(self):
        self.assertIsNone(services.safe_to_spend(None, D('100')))

    def test_rounds_down(self):
        budget = services.BudgetStatus(limit=D('3000'), spent=D('0'), remaining=D('3000'),
                                       used_percent=D('0'), state='ok', days_left=3)
        self.assertEqual(services.safe_to_spend(budget, D('100')).per_day, D('33.33'))
