from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import services
from finance.models import MonthlyBudget, Transaction

User = get_user_model()
D = Decimal


def expense_data(**overrides):
    data = {'amount': '120', 'category': 'food', 'payment_method': 'cash', 'date': timezone.localdate().isoformat()}
    data.update(overrides)
    return data


class CoinCountTests(TestCase):
    def test_thresholds(self):
        cases = [
            ('-50', 0), ('0', 0), ('0.01', 1), ('499.99', 1), ('500', 2), ('1999.99', 2),
            ('2000', 3), ('4999.99', 3), ('5000', 4), ('14999.99', 4), ('15000', 5), ('9999999', 5),
        ]
        for balance, coins in cases:
            with self.subTest(balance=balance):
                self.assertEqual(services.wallet_coin_count(D(balance)), coins)


class WalletVisualsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def visuals(self, event=None):
        return services.wallet_visuals(services.get_dashboard_summary(self.user), event)

    def add(self, kind, amount, category):
        Transaction.objects.create(
            user=self.user, kind=kind, amount=D(amount), category=category,
            payment_method='cash' if kind == 'expense' else '', date=timezone.localdate(),
        )

    def test_empty_user(self):
        self.assertEqual(self.visuals(), {'coins': 0, 'spentCoins': 0, 'budgetRing': None, 'event': None})

    def test_reflects_real_figures(self):
        self.add('income', '6000', 'tuition')
        for _ in range(3):
            self.add('expense', '100', 'food')
        MonthlyBudget.objects.create(user=self.user, month=timezone.localdate(), limit=D('1000'))
        v = self.visuals()
        self.assertEqual(v['coins'], 4)                    # balance 5700
        self.assertEqual(v['spentCoins'], 3)               # 3 expenses this month
        self.assertEqual(v['budgetRing'], {'fraction': '0.300', 'state': 'ok'})

    def test_spent_coins_capped(self):
        for _ in range(12):
            self.add('expense', '10', 'food')
        self.assertEqual(self.visuals()['spentCoins'], services.MAX_SPENT_COINS)

    def test_ring_capped_at_full_when_over_budget(self):
        MonthlyBudget.objects.create(user=self.user, month=timezone.localdate(), limit=D('100'))
        self.add('expense', '250', 'food')
        self.assertEqual(self.visuals()['budgetRing'], {'fraction': '1.000', 'state': 'over'})

    def test_only_known_events_pass_through(self):
        self.assertEqual(self.visuals('income')['event'], 'income')
        self.assertEqual(self.visuals('expense')['event'], 'expense')
        self.assertIsNone(self.visuals('<script>')['event'])

    def test_no_floats_for_money(self):
        MonthlyBudget.objects.create(user=self.user, month=timezone.localdate(), limit=D('300'))
        self.add('expense', '100', 'food')
        self.assertIsInstance(self.visuals()['budgetRing']['fraction'], str)

    def test_summary_still_four_queries(self):
        with self.assertNumQueries(4):
            services.get_dashboard_summary(self.user)


class SaveEventFlowTests(TestCase):
    """The animation flag must exist only after a real, successful save."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def setUp(self):
        self.client.force_login(self.user)

    def test_successful_save_from_dashboard_animates_once(self):
        url = reverse('finance:expense_create') + '?next=dashboard'
        response = self.client.post(url, expense_data())
        # Don't follow the redirect here: that would load the dashboard and use up the flag.
        self.assertRedirects(response, reverse('finance:dashboard'), fetch_redirect_response=False)

        first = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(first.context['wallet']['event'], 'expense')
        self.assertContains(first, '<script id="wallet-data" type="application/json">')

        refreshed = self.client.get(reverse('finance:dashboard'))
        self.assertIsNone(refreshed.context['wallet']['event'])

    def test_income_event(self):
        url = reverse('finance:income_create') + '?next=dashboard'
        self.client.post(url, {'amount': '500', 'category': 'pocket_money', 'date': timezone.localdate().isoformat()})
        self.assertEqual(self.client.get(reverse('finance:dashboard')).context['wallet']['event'], 'income')

    def test_failed_save_never_sets_the_flag(self):
        url = reverse('finance:expense_create') + '?next=dashboard'
        response = self.client.post(url, expense_data(amount='-5'))
        self.assertEqual(response.status_code, 200)            # form re-shown with errors
        self.assertNotIn('wallet_event', self.client.session)
        self.assertIsNone(self.client.get(reverse('finance:dashboard')).context['wallet']['event'])

    def test_save_from_list_page_does_not_queue_an_animation(self):
        response = self.client.post(reverse('finance:expense_create'), expense_data())
        self.assertRedirects(response, reverse('finance:transaction_list'))
        self.assertNotIn('wallet_event', self.client.session)

    def test_unknown_next_is_ignored(self):
        url = reverse('finance:expense_create') + '?next=https://evil.example/'
        response = self.client.post(url, expense_data())
        self.assertRedirects(response, reverse('finance:transaction_list'))
        self.assertNotIn('wallet_event', self.client.session)

    def test_edit_and_delete_do_not_animate(self):
        t = Transaction.objects.create(user=self.user, kind='expense', amount=D('50'), category='food',
                                       payment_method='cash', date=timezone.localdate())
        self.client.post(reverse('finance:transaction_update', args=[t.pk]) + '?next=dashboard', expense_data())
        self.client.post(reverse('finance:transaction_delete', args=[t.pk]) + '?next=dashboard')
        self.assertNotIn('wallet_event', self.client.session)

    def test_wallet_data_is_safely_escaped_json(self):
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, '"coins": 0')
        self.assertContains(response, '"budgetRing": null')
