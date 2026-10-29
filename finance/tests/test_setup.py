from django.test import TestCase
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
