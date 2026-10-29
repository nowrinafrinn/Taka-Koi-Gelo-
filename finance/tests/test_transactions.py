import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance.models import Transaction
from finance.templatetags.money import taka

User = get_user_model()
TODAY = timezone.localdate


def create(user, **overrides):
    fields = {
        'user': user,
        'kind': Transaction.Kind.EXPENSE,
        'amount': Decimal('100.00'),
        'category': Transaction.Category.FOOD,
        'payment_method': Transaction.PaymentMethod.CASH,
        'date': TODAY(),
    }
    fields.update(overrides)
    return Transaction.objects.create(**fields)


def expense_data(**overrides):
    data = {
        'amount': '250.50',
        'category': 'transport',
        'payment_method': 'bkash',
        'date': TODAY().isoformat(),
        'note': 'Rickshaw to campus',
    }
    data.update(overrides)
    return data


class LoginRequiredTests(TestCase):
    def test_every_transaction_page_requires_login(self):
        t = create(User.objects.create_user('owner', password='x'))
        login_url = reverse('accounts:login')
        for url in [
            reverse('finance:transaction_list'),
            reverse('finance:income_create'),
            reverse('finance:expense_create'),
            reverse('finance:transaction_update', args=[t.pk]),
            reverse('finance:transaction_delete', args=[t.pk]),
        ]:
            with self.subTest(url=url):
                for method in (self.client.get, self.client.post):
                    response = method(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(login_url))
        self.assertTrue(Transaction.objects.filter(pk=t.pk).exists())


class CreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def setUp(self):
        self.client.force_login(self.user)

    def test_create_expense(self):
        response = self.client.post(reverse('finance:expense_create'), expense_data())
        self.assertRedirects(response, reverse('finance:transaction_list'))
        t = Transaction.objects.get()
        self.assertEqual(t.user, self.user)
        self.assertEqual(t.kind, Transaction.Kind.EXPENSE)
        self.assertEqual(t.amount, Decimal('250.50'))

    def test_create_income_without_payment_method(self):
        response = self.client.post(reverse('finance:income_create'), {
            'amount': '3000', 'category': 'tuition', 'payment_method': '', 'date': TODAY().isoformat(),
        })
        self.assertRedirects(response, reverse('finance:transaction_list'))
        self.assertEqual(Transaction.objects.get().kind, Transaction.Kind.INCOME)

    def test_success_message_shown_after_redirect(self):
        response = self.client.post(reverse('finance:expense_create'), expense_data(), follow=True)
        self.assertContains(response, 'Expense of ৳250.50 saved.')

    def test_submitted_user_and_kind_are_ignored(self):
        # A tampered form tries to save income for another user.
        self.client.post(reverse('finance:expense_create'), expense_data(user=self.other.pk, kind='income'))
        t = Transaction.objects.get()
        self.assertEqual(t.user, self.user)
        self.assertEqual(t.kind, Transaction.Kind.EXPENSE)

    def test_invalid_amounts_rejected(self):
        for amount in ['0', '-5', 'abc', '10.005', '', '99999999999']:
            with self.subTest(amount=amount):
                response = self.client.post(reverse('finance:expense_create'), expense_data(amount=amount))
                self.assertEqual(response.status_code, 200)
                self.assertIn('amount', response.context['form'].errors)
        self.assertFalse(Transaction.objects.exists())

    def test_income_category_rejected_for_expense(self):
        response = self.client.post(reverse('finance:expense_create'), expense_data(category='tuition'))
        self.assertIn('category', response.context['form'].errors)
        self.assertFalse(Transaction.objects.exists())

    def test_expense_requires_payment_method(self):
        response = self.client.post(reverse('finance:expense_create'), expense_data(payment_method=''))
        self.assertIn('payment_method', response.context['form'].errors)

    def test_future_date_rejected(self):
        tomorrow = (TODAY() + datetime.timedelta(days=1)).isoformat()
        response = self.client.post(reverse('finance:expense_create'), expense_data(date=tomorrow))
        self.assertIn('date', response.context['form'].errors)
        self.assertFalse(Transaction.objects.exists())

    def test_form_offers_only_categories_for_its_kind(self):
        response = self.client.get(reverse('finance:income_create'))
        values = [value for value, _ in response.context['form'].fields['category'].choices]
        self.assertIn('tuition', values)
        self.assertNotIn('food', values)


class ListAndFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        other = User.objects.create_user('other', password='x')
        today = TODAY()
        cls.food = create(cls.user, category='food', date=today, note='mine-food')
        cls.bus = create(cls.user, category='transport', date=today - datetime.timedelta(days=10), note='mine-bus')
        cls.tuition = create(
            cls.user, kind='income', category='tuition', payment_method='',
            date=today - datetime.timedelta(days=40), note='mine-tuition',
        )
        create(other, note='someone-elses-secret')

    def setUp(self):
        self.client.force_login(self.user)

    def listed(self, **params):
        response = self.client.get(reverse('finance:transaction_list'), params)
        self.assertEqual(response.status_code, 200)
        return response, list(response.context['page'].object_list)

    def test_lists_only_own_transactions(self):
        response, items = self.listed()
        self.assertEqual(items, [self.food, self.bus, self.tuition])
        self.assertNotContains(response, 'someone-elses-secret')

    def test_filter_labelled_type_not_kind(self):
        response, _ = self.listed()
        self.assertEqual(response.context['filter_form'].fields['kind'].label, 'Type')
        self.assertNotContains(response, '<span>Kind</span>')

    def test_filter_by_kind(self):
        self.assertEqual(self.listed(kind='income')[1], [self.tuition])

    def test_filter_by_category(self):
        self.assertEqual(self.listed(category='transport')[1], [self.bus])

    def test_filter_by_date_range_is_inclusive(self):
        start = TODAY() - datetime.timedelta(days=10)
        self.assertEqual(self.listed(start=start.isoformat(), end=TODAY().isoformat())[1], [self.food, self.bus])

    def test_combined_filters(self):
        start = (TODAY() - datetime.timedelta(days=60)).isoformat()
        self.assertEqual(self.listed(kind='expense', category='food', start=start)[1], [self.food])

    def test_start_after_end_shows_error_and_does_not_filter(self):
        response, items = self.listed(start=TODAY().isoformat(), end='2020-01-01')
        self.assertTrue(response.context['filter_form'].errors)
        self.assertEqual(len(items), 3)

    def test_list_query_count_does_not_grow_with_rows(self):
        for _ in range(15):
            create(self.user)
        # session + user + count + one page of rows
        with self.assertNumQueries(4):
            self.client.get(reverse('finance:transaction_list'))

    def test_pagination_keeps_filters(self):
        for _ in range(25):
            create(self.user, category='food')
        response, items = self.listed(category='food')
        self.assertEqual(len(items), 20)
        self.assertContains(response, '?category=food&amp;page=2')


class OwnershipTests(TestCase):
    """Another user's transaction must look exactly like one that doesn't exist."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('owner', password='x')
        cls.intruder = User.objects.create_user('intruder', password='x')
        cls.transaction = create(cls.owner, amount=Decimal('500.00'))

    def setUp(self):
        self.client.force_login(self.intruder)

    def test_cannot_view_edit_form(self):
        response = self.client.get(reverse('finance:transaction_update', args=[self.transaction.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_edit(self):
        response = self.client.post(
            reverse('finance:transaction_update', args=[self.transaction.pk]), expense_data(amount='1'),
        )
        self.assertEqual(response.status_code, 404)
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount, Decimal('500.00'))

    def test_cannot_view_delete_confirmation(self):
        response = self.client.get(reverse('finance:transaction_delete', args=[self.transaction.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_delete(self):
        response = self.client.post(reverse('finance:transaction_delete', args=[self.transaction.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=self.transaction.pk).exists())

    def test_missing_id_gives_same_404(self):
        response = self.client.get(reverse('finance:transaction_update', args=[999999]))
        self.assertEqual(response.status_code, 404)


class EditAndDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')

    def setUp(self):
        self.client.force_login(self.user)
        self.transaction = create(self.user)

    def test_edit_form_prefilled(self):
        response = self.client.get(reverse('finance:transaction_update', args=[self.transaction.pk]))
        self.assertEqual(response.context['form'].initial['amount'], Decimal('100.00'))

    def test_edit_updates_values(self):
        response = self.client.post(
            reverse('finance:transaction_update', args=[self.transaction.pk]), expense_data(amount='75.25'),
        )
        self.assertRedirects(response, reverse('finance:transaction_list'))
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount, Decimal('75.25'))
        self.assertEqual(self.transaction.category, 'transport')

    def test_edit_cannot_change_kind(self):
        self.client.post(
            reverse('finance:transaction_update', args=[self.transaction.pk]), expense_data(kind='income'),
        )
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.kind, Transaction.Kind.EXPENSE)

    def test_invalid_edit_leaves_record_unchanged(self):
        response = self.client.post(
            reverse('finance:transaction_update', args=[self.transaction.pk]), expense_data(amount='-1'),
        )
        self.assertEqual(response.status_code, 200)
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount, Decimal('100.00'))

    def test_get_delete_only_asks_for_confirmation(self):
        response = self.client.get(reverse('finance:transaction_delete', args=[self.transaction.pk]))
        self.assertContains(response, 'Yes, delete')
        self.assertTrue(Transaction.objects.filter(pk=self.transaction.pk).exists())

    def test_post_delete_removes(self):
        response = self.client.post(reverse('finance:transaction_delete', args=[self.transaction.pk]))
        self.assertRedirects(response, reverse('finance:transaction_list'))
        self.assertFalse(Transaction.objects.filter(pk=self.transaction.pk).exists())


class TakaFilterTests(TestCase):
    def test_formats_with_south_asian_grouping(self):
        cases = {
            Decimal('0'): '৳0.00',
            Decimal('5.5'): '৳5.50',
            Decimal('999.99'): '৳999.99',
            Decimal('1000'): '৳1,000.00',
            Decimal('123456.5'): '৳1,23,456.50',
            Decimal('12345678.9'): '৳1,23,45,678.90',
            Decimal('-2500'): '-৳2,500.00',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(taka(value), expected)

    def test_non_numbers_passed_through(self):
        self.assertEqual(taka(None), None)
        self.assertEqual(taka('abc'), 'abc')
