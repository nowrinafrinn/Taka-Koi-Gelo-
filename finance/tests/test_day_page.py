import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import GoalContribution, SavingsGoal, Transaction

User = get_user_model()
D = Decimal


def add(user, kind, amount, date, category=None, method='cash', note=''):
    category = category or ('pocket_money' if kind == 'income' else 'food')
    return Transaction.objects.create(user=user, kind=kind, amount=D(amount), category=category,
                                      payment_method='' if kind == 'income' else method, date=date, note=note)


def day_url(date, **params):
    url = reverse('finance:day_detail', args=[date.isoformat()])
    return url + ('?' + '&'.join(f'{k}={v}' for k, v in params.items()) if params else '')


class DayPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.other = User.objects.create_user('other', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.day = self.today - datetime.timedelta(days=3)

    def test_lists_that_days_transactions_with_details_and_totals(self):
        add(self.user, 'expense', '520', self.day, 'food', 'cash', 'Canteen lunch')
        add(self.user, 'expense', '180', self.day, 'transport', 'bkash')
        add(self.user, 'income', '3000', self.day, 'tuition')
        add(self.user, 'expense', '999', self.day - datetime.timedelta(days=1))     # other day
        add(self.other, 'expense', '777', self.day, note='someone-elses')           # other user
        response = self.client.get(day_url(self.day))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['transactions']), 3)
        self.assertEqual((response.context['spent'], response.context['received']), (D('700.00'), D('3000.00')))
        self.assertContains(response, 'Canteen lunch')
        self.assertContains(response, 'bKash')
        self.assertNotContains(response, 'someone-elses')
        self.assertNotContains(response, '৳999.00')

    def test_goal_contributions_listed_separately(self):
        goal = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))
        GoalContribution.objects.create(goal=goal, amount=D('250'), date=self.day)
        response = self.client.get(day_url(self.day))
        self.assertEqual((response.context['to_goals'], response.context['spent']), (D('250.00'), D('0.00')))
        self.assertContains(response, 'id="day-goals"')

    def test_empty_day(self):
        response = self.client.get(day_url(self.day))
        self.assertContains(response, 'No transactions on')
        self.assertNotContains(response, 'id="day-goals"')

    def test_previous_and_next_day_links(self):
        response = self.client.get(day_url(self.day))
        self.assertEqual(response.context['previous_day'], self.day - datetime.timedelta(days=1))
        self.assertEqual(response.context['next_day'], self.day + datetime.timedelta(days=1))

    def test_no_next_day_after_today(self):
        response = self.client.get(day_url(self.today))
        self.assertIsNone(response.context['next_day'])
        self.assertContains(response, 'Today')

    def test_crosses_month_and_year_boundaries(self):
        response = self.client.get(day_url(datetime.date(2026, 1, 1)))
        self.assertEqual(response.context['previous_day'], datetime.date(2025, 12, 31))
        self.assertIn('year=2026&month=1', response.context['month_url'])

    def test_invalid_dates_are_404(self):
        for value in ['2026-02-30', 'hello', '2026-13-01', '20261001']:
            with self.subTest(value=value):
                response = self.client.get(f'/stats/day/{value}/')
                self.assertEqual(response.status_code, 404)

    def test_future_date_redirects_to_today(self):
        future = self.today + datetime.timedelta(days=5)
        self.assertRedirects(self.client.get(day_url(future)), day_url(self.today))

    def test_calendar_mode_carried_through(self):
        add(self.user, 'expense', '100', self.day)
        response = self.client.get(day_url(self.day, daily='calendar'))
        self.assertIn('daily=calendar', response.context['month_url'])
        self.assertContains(response, '?next=day&amp;daily=calendar')                  # edit/delete links
        self.assertContains(response, f'date={self.day.isoformat()}&amp;daily=calendar')  # quick add

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(day_url(self.day))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_query_count_is_small(self):
        for _ in range(10):
            add(self.user, 'expense', '10', self.day)
        with self.assertNumQueries(4):   # session, user, transactions, contributions
            self.client.get(day_url(self.day))


class ReturnToDayTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.day = self.today - datetime.timedelta(days=2)

    def expense_data(self, date, amount='120'):
        return {'amount': amount, 'category': 'food', 'payment_method': 'cash', 'date': date.isoformat()}

    def test_quick_add_prefills_the_date(self):
        response = self.client.get(reverse('finance:expense_create') + f'?next=day&date={self.day.isoformat()}')
        self.assertEqual(response.context['form'].initial['date'], self.day)
        self.assertEqual(response.context['cancel_url'], day_url(self.day))

    def test_bad_or_future_prefill_is_ignored(self):
        for value in ['nonsense', (self.today + datetime.timedelta(days=1)).isoformat()]:
            with self.subTest(value=value):
                response = self.client.get(reverse('finance:expense_create') + f'?next=day&date={value}')
                self.assertNotIn('date', response.context['form'].initial)
                self.assertEqual(response.context['cancel_url'], reverse('finance:transaction_list'))

    def test_saving_returns_to_the_saved_date_not_the_url(self):
        url = reverse('finance:expense_create') + f'?next=day&date={self.day.isoformat()}'
        other_day = self.day - datetime.timedelta(days=5)
        response = self.client.post(url, self.expense_data(other_day))   # user changed the date in the form
        self.assertRedirects(response, day_url(other_day))

    def test_edit_returns_to_new_date_and_cancel_to_old(self):
        t = add(self.user, 'expense', '50', self.day)
        url = reverse('finance:transaction_update', args=[t.pk]) + '?next=day'
        self.assertEqual(self.client.get(url).context['cancel_url'], day_url(self.day))
        moved = self.day - datetime.timedelta(days=1)
        self.assertRedirects(self.client.post(url, self.expense_data(moved, '75')), day_url(moved))

    def test_failed_edit_keeps_cancel_on_original_day(self):
        t = add(self.user, 'expense', '50', self.day)
        url = reverse('finance:transaction_update', args=[t.pk]) + '?next=day'
        bad_date = (self.today + datetime.timedelta(days=3)).isoformat()
        response = self.client.post(url, {**self.expense_data(self.day), 'date': bad_date})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cancel_url'], day_url(self.day))

    def test_delete_returns_to_the_day(self):
        t = add(self.user, 'expense', '50', self.day)
        url = reverse('finance:transaction_delete', args=[t.pk]) + '?next=day&daily=calendar'
        self.assertEqual(self.client.get(url).context['cancel_url'], day_url(self.day, daily='calendar'))
        self.assertRedirects(self.client.post(url), day_url(self.day, daily='calendar'))
        self.assertFalse(Transaction.objects.filter(pk=t.pk).exists())

    def test_without_next_behaviour_is_unchanged(self):
        t = add(self.user, 'expense', '50', self.day)
        response = self.client.post(reverse('finance:transaction_update', args=[t.pk]), self.expense_data(self.day))
        self.assertRedirects(response, reverse('finance:transaction_list'))

    def test_other_users_transactions_still_404(self):
        other = User.objects.create_user('other', password='x')
        t = add(other, 'expense', '50', self.day)
        for name in ['finance:transaction_update', 'finance:transaction_delete']:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[t.pk]) + '?next=day').status_code, 404)


class DayLinksTests(TestCase):
    def test_bars_and_calendar_days_link_to_day_pages(self):
        user = User.objects.create_user('mitu', password='x')
        self.client.force_login(user)
        today = timezone.localdate()
        add(user, 'expense', '100', today)
        bars = self.client.get(reverse('finance:stats'))
        self.assertContains(bars, f'href="{day_url(today)}"')
        calendar = self.client.get(reverse('finance:stats') + '?daily=calendar')
        self.assertContains(calendar, f'href="{day_url(today)}?daily=calendar"')
        tomorrow = today + datetime.timedelta(days=1)
        if tomorrow.month == today.month:
            self.assertNotContains(calendar, f'href="{day_url(tomorrow)}')            # future days aren't links
