from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()
PASSWORD = 'sturdy-Pass-2026'


class SignUpTests(TestCase):
    url = reverse('accounts:signup')

    def post_signup(self, username='mitu', password1=PASSWORD, password2=PASSWORD):
        return self.client.post(self.url, {'username': username, 'password1': password1, 'password2': password2})

    def test_page_renders(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_signup_creates_user_logs_in_and_redirects_to_dashboard(self):
        response = self.post_signup()
        self.assertRedirects(response, reverse('finance:dashboard'))
        user = User.objects.get(username='mitu')
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_password_is_hashed_not_stored_plainly(self):
        self.post_signup()
        user = User.objects.get(username='mitu')
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_mismatched_passwords_rejected(self):
        response = self.post_signup(password2='different-Pass-2026')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_weak_password_rejected(self):
        response = self.post_signup(password1='12345678', password2='12345678')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user('mitu', password=PASSWORD)
        response = self.post_signup()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_logged_in_user_is_redirected_away(self):
        self.client.force_login(User.objects.create_user('mitu', password=PASSWORD))
        self.assertRedirects(self.client.get(self.url), reverse('finance:dashboard'))


class LoginLogoutTests(TestCase):
    login_url = reverse('accounts:login')
    dashboard_url = reverse('finance:dashboard')

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('sakib', password=PASSWORD)

    def test_correct_credentials_log_in(self):
        response = self.client.post(self.login_url, {'username': 'sakib', 'password': PASSWORD})
        self.assertRedirects(response, self.dashboard_url)

    def test_wrong_password_shows_error_and_stays_logged_out(self):
        response = self.client.post(self.login_url, {'username': 'sakib', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_returns_to_requested_page(self):
        response = self.client.post(
            f'{self.login_url}?next={self.dashboard_url}',
            {'username': 'sakib', 'password': PASSWORD, 'next': self.dashboard_url},
        )
        self.assertRedirects(response, self.dashboard_url)

    def test_login_ignores_next_pointing_to_another_site(self):
        # Prevents "open redirect" phishing: ?next=https://evil.example
        response = self.client.post(
            self.login_url,
            {'username': 'sakib', 'password': PASSWORD, 'next': 'https://evil.example/'},
        )
        self.assertRedirects(response, self.dashboard_url)

    def test_logged_in_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(self.login_url), self.dashboard_url)

    def test_logout_by_post(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:logout'))
        self.assertRedirects(response, reverse('finance:home'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_by_get_is_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)

    def test_login_without_csrf_token_is_rejected(self):
        # The normal test client skips CSRF checks; this one enforces them.
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(self.login_url, {'username': 'sakib', 'password': PASSWORD})
        self.assertEqual(response.status_code, 403)


class ProtectedPageTests(TestCase):
    dashboard_url = reverse('finance:dashboard')

    def test_anonymous_user_is_sent_to_login_with_next(self):
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.dashboard_url}")

    def test_logged_in_user_sees_dashboard(self):
        self.client.force_login(User.objects.create_user('ria', password=PASSWORD))
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hi, ria')

    def test_home_sends_logged_in_user_to_dashboard(self):
        self.client.force_login(User.objects.create_user('ria', password=PASSWORD))
        self.assertRedirects(self.client.get(reverse('finance:home')), self.dashboard_url)
