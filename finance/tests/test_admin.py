from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdminPagesTests(TestCase):
    def setUp(self):
        admin_user = get_user_model().objects.create_superuser('admin', password='test-pass-123')
        self.client.force_login(admin_user)

    def test_admin_pages_load(self):
        for name in [
            'admin:finance_transaction_changelist',
            'admin:finance_transaction_add',
            'admin:finance_monthlybudget_changelist',
            'admin:finance_monthlybudget_add',
        ]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
