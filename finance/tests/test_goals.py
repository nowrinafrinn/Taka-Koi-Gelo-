import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from finance import services
from finance.models import GoalContribution, SavingsGoal, Transaction

User = get_user_model()
D = Decimal
TODAY = datetime.date(2026, 10, 20)


def goal(user, name='New phone', target='20000', target_date=None):
    return SavingsGoal.objects.create(user=user, name=name, target_amount=D(target), target_date=target_date)


def contribute(g, amount, date=TODAY, note=''):
    return GoalContribution.objects.create(goal=g, amount=D(amount), date=date, note=note)


def add(user, kind, amount, date, category=None):
    category = category or ('pocket_money' if kind == 'income' else 'food')
    return Transaction.objects.create(
        user=user, kind=kind, amount=D(amount), category=category,
        payment_method='' if kind == 'income' else 'cash', date=date,
    )


class ModelValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def test_target_must_be_positive(self):
        for target in ['0', '-100']:
            with self.subTest(target=target), self.assertRaises(ValidationError):
                SavingsGoal(user=self.user, name='x', target_amount=D(target)).full_clean()

    def test_database_rejects_non_positive_values(self):
        with self.assertRaises(IntegrityError):
            goal(self.user, target='0')

    def test_contribution_must_be_positive_and_not_in_future(self):
        g = goal(self.user)
        for amount, date in [('0', TODAY), ('-5', TODAY), ('10', timezone.localdate() + datetime.timedelta(days=1))]:
            with self.subTest(amount=amount, date=date), self.assertRaises(ValidationError):
                GoalContribution(goal=g, amount=D(amount), date=date).full_clean()

    def test_goal_names_unique_per_user_only(self):
        other = User.objects.create_user('other', password='x')
        goal(self.user, 'Trip')
        goal(other, 'Trip')                     # fine: different user
        with self.assertRaises(IntegrityError):
            goal(self.user, 'Trip')

    def test_deleting_goal_deletes_its_contributions(self):
        g = goal(self.user)
        contribute(g, '100')
        g.delete()
        self.assertFalse(GoalContribution.objects.exists())


class ProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def test_progress_figures(self):
        g = goal(self.user, target='20000')
        contribute(g, '5000')
        contribute(g, '2500.50')
        p = services.goal_progress(g, TODAY)
        self.assertEqual((p.contributed, p.remaining, p.percent, p.is_complete), (D('7500.50'), D('12499.50'), D('37.5'), False))

    def test_goal_with_no_contributions(self):
        p = services.goal_progress(goal(self.user), TODAY)
        self.assertEqual((p.contributed, p.remaining, p.percent), (D('0.00'), D('20000.00'), D('0.0')))

    def test_completed_and_over_contribution(self):
        g = goal(self.user, target='1000')
        contribute(g, '1200')
        p = services.goal_progress(g, TODAY)
        self.assertTrue(p.is_complete)
        self.assertEqual((p.remaining, p.percent, p.bar_percent), (D('0.00'), D('120.0'), D('100')))

    def test_exactly_at_target_is_complete(self):
        g = goal(self.user, target='1000')
        contribute(g, '1000')
        self.assertTrue(services.goal_progress(g, TODAY).is_complete)

    def test_overdue_only_when_unfinished(self):
        late = goal(self.user, 'Late', target_date=datetime.date(2026, 9, 1))
        done = goal(self.user, 'Done', target='10', target_date=datetime.date(2026, 9, 1))
        contribute(done, '10')
        self.assertTrue(services.goal_progress(late, TODAY).is_overdue)
        self.assertFalse(services.goal_progress(done, TODAY).is_overdue)

    def test_list_splits_active_and_completed_in_one_query(self):
        a, b = goal(self.user, 'A', '100'), goal(self.user, 'B', '100')
        contribute(a, '40')
        contribute(b, '100')
        with self.assertNumQueries(1):
            active, completed = services.goals_with_progress(self.user, TODAY)
        self.assertEqual([p.goal.name for p in active], ['A'])
        self.assertEqual([p.goal.name for p in completed], ['B'])
        self.assertEqual(active[0].contributed, D('40.00'))


class SeparationFromSpendingTests(TestCase):
    """Contributions must never be counted as expenses or change existing figures."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def test_contributions_do_not_touch_balance_expenses_or_budget(self):
        add(self.user, 'income', '10000', TODAY)
        add(self.user, 'expense', '3000', TODAY)
        before = services.get_dashboard_summary(self.user, TODAY)
        contribute(goal(self.user), '4000')
        after = services.get_dashboard_summary(self.user, TODAY)
        self.assertEqual(
            (after.balance, after.month_income, after.month_expenses, after.categories),
            (before.balance, before.month_income, before.month_expenses, before.categories),
        )

    def test_surplus_unchanged_and_savings_reported_separately(self):
        add(self.user, 'income', '10000', TODAY)
        add(self.user, 'expense', '3000', TODAY)
        contribute(goal(self.user), '2500')
        s = services.get_month_report(self.user, 2026, 10, TODAY).stat
        self.assertEqual((s.net, s.expenses, s.contributions, s.savings_rate), (D('7000.00'), D('3000.00'), D('2500.00'), D('25.0')))

    def test_savings_rate_is_na_without_income(self):
        contribute(goal(self.user), '500')
        s = services.get_month_report(self.user, 2026, 10, TODAY).stat
        self.assertEqual(s.contributions, D('500.00'))
        self.assertIsNone(s.savings_rate)
        self.assertIsNone(services.savings_rate(D('500'), D('0')))

    def test_contributions_bucket_by_their_own_date_and_owner(self):
        other = User.objects.create_user('other', password='x')
        g = goal(self.user)
        contribute(g, '100', datetime.date(2026, 9, 30))
        contribute(g, '200', datetime.date(2026, 10, 1))
        contribute(goal(other), '9999', datetime.date(2026, 10, 2))
        c = services.get_year_comparison(self.user, 2026, TODAY)
        self.assertEqual((c.months[8].contributions, c.months[9].contributions), (D('100.00'), D('200.00')))
        self.assertEqual(c.total_contributions, D('300.00'))
        self.assertEqual(services.total_set_aside(self.user), D('300.00'))

    def test_year_savings_rate(self):
        add(self.user, 'income', '8000', datetime.date(2026, 3, 1))
        contribute(goal(self.user), '1000', datetime.date(2026, 3, 2))
        self.assertEqual(services.get_year_comparison(self.user, 2026, TODAY).savings_rate, D('12.5'))


class GoalViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)

    def test_empty_state(self):
        response = self.client.get(reverse('finance:goal_list'))
        self.assertContains(response, 'No savings goals yet')

    def test_card_has_add_money_button(self):
        goal = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))
        detail = reverse('finance:goal_detail', args=[goal.pk])
        response = self.client.get(reverse('finance:goal_list'))
        self.assertContains(response, f'href="{detail}#add">+ Add money')
        self.assertContains(self.client.get(detail), 'id="add"')

    def test_create_goal(self):
        response = self.client.post(reverse('finance:goal_create'),
                                    {'name': '  Laptop ', 'target_amount': '60000', 'target_date': ''})
        g = SavingsGoal.objects.get()
        self.assertRedirects(response, reverse('finance:goal_detail', args=[g.pk]))
        self.assertEqual((g.user, g.name, g.target_amount, g.target_date), (self.user, 'Laptop', D('60000.00'), None))

    def test_invalid_goal_inputs(self):
        cases = [
            {'name': 'x', 'target_amount': '0'},
            {'name': 'x', 'target_amount': '-5'},
            {'name': 'x', 'target_amount': 'abc'},
            {'name': '', 'target_amount': '100'},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(reverse('finance:goal_create'), data).status_code, 200)
        self.assertFalse(SavingsGoal.objects.exists())

    def test_duplicate_name_gives_friendly_error(self):
        goal(self.user, 'Trip')
        response = self.client.post(reverse('finance:goal_create'), {'name': 'trip', 'target_amount': '100'})
        self.assertContains(response, 'You already have a goal with this name.')

    def test_list_shows_progress_and_completed_section(self):
        done = goal(self.user, 'Bag', '500')
        contribute(done, '500')
        contribute(goal(self.user, 'Phone', '20000'), '5000')
        response = self.client.get(reverse('finance:goal_list'))
        self.assertContains(response, 'In progress')
        self.assertContains(response, 'Completed')
        self.assertContains(response, '৳15,000.00 to go')

    def test_edit_goal(self):
        g = goal(self.user)
        self.client.post(reverse('finance:goal_update', args=[g.pk]),
                         {'name': 'Better phone', 'target_amount': '25000', 'target_date': '2027-01-31'})
        g.refresh_from_db()
        self.assertEqual((g.name, g.target_amount, g.target_date), ('Better phone', D('25000.00'), datetime.date(2027, 1, 31)))

    def test_delete_goal_needs_post_and_removes_contributions(self):
        g = goal(self.user)
        contribute(g, '100')
        response = self.client.get(reverse('finance:goal_delete', args=[g.pk]))
        self.assertContains(response, '1 contribution')
        self.assertTrue(SavingsGoal.objects.exists())
        self.client.post(reverse('finance:goal_delete', args=[g.pk]))
        self.assertFalse(SavingsGoal.objects.exists())
        self.assertFalse(GoalContribution.objects.exists())

    def test_add_edit_delete_contribution(self):
        g = goal(self.user)
        today = timezone.localdate().isoformat()
        response = self.client.post(reverse('finance:contribution_create', args=[g.pk]),
                                    {'amount': '1500', 'date': today, 'note': 'tuition'})
        self.assertRedirects(response, reverse('finance:goal_detail', args=[g.pk]))
        c = GoalContribution.objects.get()
        self.assertEqual((c.goal, c.amount), (g, D('1500.00')))
        self.client.post(reverse('finance:contribution_update', args=[c.pk]), {'amount': '1750', 'date': today})
        c.refresh_from_db()
        self.assertEqual(c.amount, D('1750.00'))
        self.client.post(reverse('finance:contribution_delete', args=[c.pk]))
        self.assertFalse(GoalContribution.objects.exists())

    def test_invalid_contributions_rejected(self):
        g = goal(self.user)
        tomorrow = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        for data in [{'amount': '0', 'date': '2026-01-01'}, {'amount': '-1', 'date': '2026-01-01'},
                     {'amount': '10', 'date': tomorrow}, {'amount': '', 'date': '2026-01-01'}]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(reverse('finance:contribution_create', args=[g.pk]), data).status_code, 200)
        self.assertFalse(GoalContribution.objects.exists())

    def test_contribution_never_creates_a_transaction(self):
        g = goal(self.user)
        self.client.post(reverse('finance:contribution_create', args=[g.pk]),
                         {'amount': '500', 'date': timezone.localdate().isoformat()})
        self.assertEqual(GoalContribution.objects.count(), 1)
        self.assertFalse(Transaction.objects.exists())

    def test_dashboard_shows_set_aside_without_changing_balance(self):
        add(self.user, 'income', '10000', timezone.localdate())
        contribute(goal(self.user), '4000', timezone.localdate())
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, '৳10,000.00')                     # balance unchanged
        self.assertContains(response, '৳4,000.00 set aside for goals')
        self.assertContains(response, '৳6,000.00 not set aside')

    def test_stats_show_contributions_and_na_rate(self):
        contribute(goal(self.user), '300', timezone.localdate())
        response = self.client.get(reverse('finance:stats'))
        self.assertContains(response, 'Put towards goals')
        self.assertContains(response, '<strong>N/A</strong> (no income recorded)')


class GoalOwnershipTests(TestCase):
    """Another user's goal or contribution must look exactly like a missing one."""

    def setUp(self):
        owner = User.objects.create_user('owner', password='x')
        self.goal = goal(owner)
        self.contribution = contribute(self.goal, '100')
        self.client.force_login(User.objects.create_user('intruder', password='x'))

    def test_every_goal_url_is_404_for_other_users(self):
        g, c = self.goal.pk, self.contribution.pk
        today = TODAY.isoformat()
        cases = [
            ('get', reverse('finance:goal_detail', args=[g]), {}),
            ('get', reverse('finance:goal_update', args=[g]), {}),
            ('post', reverse('finance:goal_update', args=[g]), {'name': 'pwned', 'target_amount': '1'}),
            ('get', reverse('finance:goal_delete', args=[g]), {}),
            ('post', reverse('finance:goal_delete', args=[g]), {}),
            ('post', reverse('finance:contribution_create', args=[g]), {'amount': '5', 'date': today}),
            ('get', reverse('finance:contribution_update', args=[c]), {}),
            ('post', reverse('finance:contribution_update', args=[c]), {'amount': '1', 'date': today}),
            ('post', reverse('finance:contribution_delete', args=[c]), {}),
        ]
        for method, url, data in cases:
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url, data).status_code, 404)
        self.goal.refresh_from_db()
        self.contribution.refresh_from_db()
        self.assertEqual((self.goal.name, self.contribution.amount), ('New phone', D('100.00')))
        self.assertEqual(GoalContribution.objects.count(), 1)

    def test_list_shows_only_own_goals(self):
        self.assertContains(self.client.get(reverse('finance:goal_list')), 'No savings goals yet')

    def test_login_required(self):
        anonymous = Client()
        for url in [reverse('finance:goal_list'), reverse('finance:goal_create'),
                    reverse('finance:goal_detail', args=[self.goal.pk])]:
            with self.subTest(url=url):
                self.assertEqual(anonymous.get(url).status_code, 302)

    def test_csrf_required_for_goal_changes(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.goal.user)
        for url in [reverse('finance:goal_create'), reverse('finance:goal_delete', args=[self.goal.pk]),
                    reverse('finance:contribution_create', args=[self.goal.pk]),
                    reverse('finance:contribution_delete', args=[self.contribution.pk])]:
            with self.subTest(url=url):
                self.assertEqual(strict.post(url, {}).status_code, 403)
        self.assertEqual((SavingsGoal.objects.count(), GoalContribution.objects.count()), (1, 1))


class SavingsRateWordingTests(TestCase):
    def test_rate_above_100_is_explained(self):
        user = User.objects.create_user('mitu', password='x')
        self.client.force_login(user)
        today = timezone.localdate()
        add(user, 'income', '1000', today)
        contribute(goal(user), '1500', today)
        response = self.client.get(reverse('finance:stats'))
        self.assertContains(response, '<strong>150.0%</strong> of recorded income, so more went to goals')


class OwnerPagesRenderTests(TestCase):
    def test_owner_sees_edit_and_confirm_pages_with_current_values(self):
        user = User.objects.create_user('mitu', password='x')
        self.client.force_login(user)
        g = goal(user, 'Trip', '6000')
        c = contribute(g, '250', note='first')
        edit_goal = self.client.get(reverse('finance:goal_update', args=[g.pk]))
        self.assertEqual(edit_goal.context['form'].initial['name'], 'Trip')
        edit_contribution = self.client.get(reverse('finance:contribution_update', args=[c.pk]))
        self.assertEqual(edit_contribution.context['form'].initial['amount'], D('250.00'))
        confirm = self.client.get(reverse('finance:contribution_delete', args=[c.pk]))
        self.assertContains(confirm, 'Yes, delete')
        self.assertTrue(GoalContribution.objects.filter(pk=c.pk).exists())   # GET deletes nothing

    def test_readable_names(self):
        g = goal(User.objects.create_user('mitu', password='x'), 'Trip', '6000')
        c = contribute(g, '250', date=datetime.date(2026, 10, 5))
        g.refresh_from_db()
        c.refresh_from_db()   # read back the stored 2-decimal values
        self.assertEqual(str(g), 'Trip (৳6000.00)')
        self.assertEqual(str(c), '৳250.00 to Trip on 2026-10-05')
