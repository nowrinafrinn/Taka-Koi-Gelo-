import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import MonthlyBudget, Transaction

User = get_user_model()


class DashboardViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def setUp(self):
        self.client.force_login(self.user)

    def test_empty_dashboard_renders_with_zeros(self):
        response = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '৳0.00')
        self.assertContains(response, 'No budget for this month yet')
        self.assertContains(response, 'Nothing recorded yet')

    def test_dashboard_shows_real_figures(self):
        today = timezone.localdate()
        Transaction.objects.create(user=self.user, kind='income', amount=Decimal('15000'),
                                   category='tuition', date=today)
        Transaction.objects.create(user=self.user, kind='expense', amount=Decimal('1234.50'),
                                   category='food', payment_method='cash', date=today)
        MonthlyBudget.objects.create(user=self.user, month=today, limit=Decimal('8000'))
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, '৳13,765.50')   # balance
        self.assertContains(response, '৳15,000.00')   # month income
        self.assertContains(response, '৳1,234.50')    # month spending
        self.assertContains(response, '৳6,765.50')    # budget remaining

    def test_over_budget_is_shown(self):
        today = timezone.localdate()
        MonthlyBudget.objects.create(user=self.user, month=today, limit=Decimal('1000'))
        Transaction.objects.create(user=self.user, kind='expense', amount=Decimal('1500'),
                                   category='food', payment_method='cash', date=today)
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, 'Over budget by')
        self.assertContains(response, 'budget-over')


class WalletAssetsTests(TestCase):
    """The 3D wallet is an enhancement: the page must work without it."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('mitu', password='x'))

    def test_dashboard_loads_pinned_three_and_wallet_module(self):
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, '<script type="importmap">')
        self.assertContains(response, '/static/vendor/three-0.186.1/three.module.js')
        self.assertContains(response, '<script type="module" src="/static/js/wallet.js">')

    def test_static_fallback_and_figures_are_in_the_html(self):
        response = self.client.get(reverse('finance:dashboard'))
        self.assertContains(response, 'id="wallet-stage"')
        self.assertContains(response, '<svg viewBox="0 0 260 200"')   # fallback illustration
        self.assertContains(response, 'Total balance')              # figures do not need JS

    def test_vendored_files_exist(self):
        from django.contrib.staticfiles import finders
        for path in [
            'vendor/three-0.186.1/three.module.js',
            'vendor/three-0.186.1/three.core.js',
            'vendor/three-0.186.1/addons/environments/RoomEnvironment.js',
            'js/wallet.js',
        ]:
            with self.subTest(path=path):
                self.assertIsNotNone(finders.find(path))


class BudgetViewTests(TestCase):
    url = reverse('finance:budget_edit')

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def setUp(self):
        self.client.force_login(self.user)
        self.month = timezone.localdate().replace(day=1)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {'limit': '5000'}).status_code, 302)
        self.assertFalse(MonthlyBudget.objects.exists())

    def test_creates_budget_for_current_month(self):
        response = self.client.post(self.url, {'limit': '5000'})
        self.assertRedirects(response, reverse('finance:dashboard'))
        b = MonthlyBudget.objects.get()
        self.assertEqual((b.user, b.month, b.limit), (self.user, self.month, Decimal('5000.00')))

    def test_updates_instead_of_duplicating(self):
        self.client.post(self.url, {'limit': '5000'})
        self.client.post(self.url, {'limit': '6500'})
        self.assertEqual(MonthlyBudget.objects.get().limit, Decimal('6500.00'))

    def test_invalid_limits_rejected(self):
        for limit in ['0', '-100', 'abc', '']:
            with self.subTest(limit=limit):
                response = self.client.post(self.url, {'limit': limit})
                self.assertEqual(response.status_code, 200)
                self.assertIn('limit', response.context['form'].errors)
        self.assertFalse(MonthlyBudget.objects.exists())

    def test_prefills_from_previous_month(self):
        last_month = (self.month - datetime.timedelta(days=1)).replace(day=1)
        MonthlyBudget.objects.create(user=self.user, month=last_month, limit=Decimal('4200'))
        response = self.client.get(self.url)
        self.assertEqual(response.context['form'].initial['limit'], Decimal('4200.00'))

    def test_does_not_touch_other_users_budget(self):
        MonthlyBudget.objects.create(user=self.other, month=self.month, limit=Decimal('9999'))
        self.client.post(self.url, {'limit': '5000'})
        self.assertEqual(MonthlyBudget.objects.get(user=self.other).limit, Decimal('9999.00'))
        self.assertEqual(MonthlyBudget.objects.get(user=self.user).limit, Decimal('5000.00'))
