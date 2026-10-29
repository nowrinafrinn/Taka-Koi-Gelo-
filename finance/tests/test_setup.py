from unittest import mock

from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse


class SetupSmokeTests(TestCase):
    def test_healthz_returns_ok(self):
        response = self.client.get(reverse('healthz'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok')

    def test_healthz_rejects_post(self):
        response = self.client.post(reverse('healthz'))
        self.assertEqual(response.status_code, 405)

    def test_home_page_renders(self):
        response = self.client.get(reverse('finance:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Taka Koi Gelo?')


class DatabaseHealthTests(TestCase):
    url = reverse('healthz_db')

    def test_ok_when_database_reachable(self):
        response = self.client.get(self.url)
        self.assertEqual((response.status_code, response.content), (200, b'ok'))

    @override_settings(CRON_SECRET='test-cron-secret')
    def test_requires_bearer_token_when_secret_set(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, headers={'Authorization': 'Bearer wrong'}).status_code, 401)
        ok = self.client.get(self.url, headers={'Authorization': 'Bearer test-cron-secret'})
        self.assertEqual(ok.status_code, 200)

    def test_503_when_database_down(self):
        with mock.patch('config.views.connection.cursor', side_effect=OperationalError('down')):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'down', response.content)   # no internal error details leak
