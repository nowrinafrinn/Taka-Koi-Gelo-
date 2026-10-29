import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from finance.models import MonthlyBudget, Transaction

User = get_user_model()


def make_transaction(user, **overrides):
    """Build (not save) a valid expense, with any field overridden."""
    fields = {
        'user': user,
        'kind': Transaction.Kind.EXPENSE,
        'amount': Decimal('120.50'),
        'category': Transaction.Category.FOOD,
        'payment_method': Transaction.PaymentMethod.CASH,
        'date': timezone.localdate(),
    }
    fields.update(overrides)
    return Transaction(**fields)


class TransactionValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('rafi', password='test-pass-123')

    def assertInvalid(self, transaction, field):
        with self.assertRaises(ValidationError) as ctx:
            transaction.full_clean()
        self.assertIn(field, ctx.exception.message_dict)

    def test_valid_expense_saves(self):
        t = make_transaction(self.user)
        t.full_clean()
        t.save()
        self.assertEqual(Transaction.objects.count(), 1)

    def test_valid_income_without_payment_method(self):
        t = make_transaction(
            self.user, kind=Transaction.Kind.INCOME,
            category=Transaction.Category.TUITION, payment_method='',
        )
        t.full_clean()  # does not raise

    def test_income_may_record_payment_method(self):
        t = make_transaction(
            self.user, kind=Transaction.Kind.INCOME,
            category=Transaction.Category.TUITION, payment_method=Transaction.PaymentMethod.BKASH,
        )
        t.full_clean()  # does not raise

    def test_zero_amount_rejected(self):
        self.assertInvalid(make_transaction(self.user, amount=Decimal('0')), 'amount')

    def test_negative_amount_rejected(self):
        self.assertInvalid(make_transaction(self.user, amount=Decimal('-50')), 'amount')

    def test_more_than_two_decimal_places_rejected(self):
        self.assertInvalid(make_transaction(self.user, amount=Decimal('10.005')), 'amount')

    def test_amount_too_large_rejected(self):
        self.assertInvalid(make_transaction(self.user, amount=Decimal('10000000000.00')), 'amount')

    def test_smallest_amount_accepted(self):
        make_transaction(self.user, amount=Decimal('0.01')).full_clean()

    def test_expense_requires_payment_method(self):
        self.assertInvalid(make_transaction(self.user, payment_method=''), 'payment_method')

    def test_expense_cannot_use_income_category(self):
        self.assertInvalid(make_transaction(self.user, category=Transaction.Category.TUITION), 'category')

    def test_income_cannot_use_expense_category(self):
        t = make_transaction(self.user, kind=Transaction.Kind.INCOME, category=Transaction.Category.FOOD)
        self.assertInvalid(t, 'category')

    def test_unknown_category_rejected(self):
        self.assertInvalid(make_transaction(self.user, category='crypto'), 'category')

    def test_future_date_rejected(self):
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        self.assertInvalid(make_transaction(self.user, date=tomorrow), 'date')

    def test_today_uses_dhaka_time_not_utc(self):
        # 19:00 UTC on 31 Oct is already 01:00 on 1 Nov in Dhaka (UTC+6).
        utc_now = datetime.datetime(2026, 10, 31, 19, 0, tzinfo=datetime.timezone.utc)
        with mock.patch('django.utils.timezone.now', return_value=utc_now):
            make_transaction(self.user, date=datetime.date(2026, 11, 1)).full_clean()

    def test_database_rejects_non_positive_amount_even_without_validation(self):
        # save() skips full_clean(), so this proves the CHECK constraint works.
        with self.assertRaises(IntegrityError):
            make_transaction(self.user, amount=Decimal('0')).save()

    def test_amount_round_trips_exactly(self):
        t = make_transaction(self.user, amount=Decimal('1234.56'))
        t.save()
        t.refresh_from_db()
        self.assertEqual(t.amount, Decimal('1234.56'))
        self.assertIsInstance(t.amount, Decimal)

    def test_newest_date_listed_first(self):
        today = timezone.localdate()
        older = make_transaction(self.user, date=today - datetime.timedelta(days=3))
        older.save()
        newer = make_transaction(self.user, date=today)
        newer.save()
        self.assertEqual(list(Transaction.objects.all()), [newer, older])

    def test_deleting_user_deletes_their_transactions(self):
        make_transaction(self.user).save()
        self.user.delete()
        self.assertEqual(Transaction.objects.count(), 0)


class MonthlyBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('nadia', password='test-pass-123')
        cls.other = User.objects.create_user('tanvir', password='test-pass-123')

    def test_month_is_normalised_to_first_day(self):
        budget = MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 17), limit=Decimal('8000'))
        budget.refresh_from_db()
        self.assertEqual(budget.month, datetime.date(2026, 10, 1))

    def test_one_budget_per_user_per_month_in_database(self):
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=Decimal('8000'))
        with self.assertRaises(IntegrityError):
            MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 20), limit=Decimal('9000'))

    def test_duplicate_month_caught_by_validation(self):
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=Decimal('8000'))
        duplicate = MonthlyBudget(user=self.user, month=datetime.date(2026, 10, 20), limit=Decimal('9000'))
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_different_users_can_budget_same_month(self):
        MonthlyBudget.objects.create(user=self.user, month=datetime.date(2026, 10, 1), limit=Decimal('8000'))
        MonthlyBudget.objects.create(user=self.other, month=datetime.date(2026, 10, 1), limit=Decimal('5000'))
        self.assertEqual(MonthlyBudget.objects.count(), 2)

    def test_zero_limit_rejected(self):
        budget = MonthlyBudget(user=self.user, month=datetime.date(2026, 10, 1), limit=Decimal('0'))
        with self.assertRaises(ValidationError):
            budget.full_clean()


class StringRepresentationTests(TestCase):
    def test_readable_names_in_admin(self):
        user = User.objects.create_user('mim', password='test-pass-123')
        t = make_transaction(user, amount=Decimal('250.00'), date=datetime.date(2026, 10, 5))
        self.assertEqual(str(t), 'Expense ৳250.00 (Food) on 2026-10-05')
        b = MonthlyBudget(user=user, month=datetime.date(2026, 10, 1), limit=Decimal('5000.00'))
        self.assertEqual(str(b), 'October 2026: ৳5000.00')
