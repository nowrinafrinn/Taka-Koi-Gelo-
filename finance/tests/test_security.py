"""Security checks that cut across features."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import MonthlyBudget, Transaction

User = get_user_model()


def make_expense(user, **overrides):
    fields = {
        'user': user, 'kind': 'expense', 'amount': Decimal('100'), 'category': 'food',
        'payment_method': 'cash', 'date': timezone.localdate(),
    }
    fields.update(overrides)
    return Transaction.objects.create(**fields)


class CsrfTests(TestCase):
    """Every state-changing form must be rejected without a CSRF token."""

    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def test_state_changing_posts_need_a_token(self):
        t = make_expense(self.user)
        today = timezone.localdate().isoformat()
        cases = [
            (reverse('finance:expense_create'), {'amount': '5', 'category': 'food', 'payment_method': 'cash', 'date': today}),
            (reverse('finance:transaction_update', args=[t.pk]), {'amount': '1', 'category': 'food', 'payment_method': 'cash', 'date': today}),
            (reverse('finance:transaction_delete', args=[t.pk]), {}),
            (reverse('finance:budget_edit'), {'limit': '5000'}),
            (reverse('accounts:logout'), {}),
        ]
        for url, data in cases:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)
        t.refresh_from_db()
        self.assertEqual(t.amount, Decimal('100.00'))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertFalse(MonthlyBudget.objects.exists())


class OutputEscapingTests(TestCase):
    """User-typed text must be shown as text, never run as HTML/JS."""

    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        make_expense(self.user, note='<script>alert("xss")</script>')

    def test_note_is_escaped_in_the_list(self):
        response = self.client.get(reverse('finance:transaction_list'))
        self.assertNotContains(response, '<script>alert("xss")</script>')
        self.assertContains(response, '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;')

    def test_hostile_username_is_escaped(self):
        hostile = User.objects.create_user('a<b>"c', password='x')   # Django's validator would block this at sign-up
        self.client.force_login(hostile)
        response = self.client.get(reverse('finance:dashboard'))
        self.assertNotContains(response, 'a<b>"c')
        self.assertContains(response, 'a&lt;b&gt;&quot;c')

    def test_wallet_json_cannot_break_out_of_its_script_tag(self):
        response = self.client.get(reverse('finance:dashboard'))
        html = response.content.decode()
        start = html.index('<script id="wallet-data"')
        block = html[start:html.index('</script>', start)]
        self.assertNotIn('<', block[len('<script'):])


class AdminAccessTests(TestCase):
    def test_regular_user_cannot_open_admin(self):
        self.client.force_login(User.objects.create_user('mitu', password='x'))
        response = self.client.get(reverse('admin:finance_transaction_changelist'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin:login'), response.url)


class ErrorPageTests(TestCase):
    def test_custom_404_page(self):
        # The test runner runs with DEBUG=False, so this is the real 404 page.
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'We couldn’t find that page', status_code=404)

    def test_other_users_transaction_gets_the_same_404_page(self):
        owner = User.objects.create_user('owner', password='x')
        t = make_expense(owner)
        self.client.force_login(User.objects.create_user('intruder', password='x'))
        response = self.client.get(reverse('finance:transaction_update', args=[t.pk]))
        self.assertContains(response, 'We couldn’t find that page', status_code=404)

    def test_500_template_renders_without_context(self):
        from django.template.loader import render_to_string
        html = render_to_string('500.html')
        self.assertIn('Something went wrong on our side', html)


class HealthCheckTests(TestCase):
    def test_healthz_reveals_nothing_and_sets_security_headers(self):
        response = self.client.get(reverse('healthz'))
        self.assertEqual(response.content, b'ok')                       # no versions, no DB details
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')
