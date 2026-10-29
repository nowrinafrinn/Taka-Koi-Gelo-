import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from finance import charts, services
from finance.models import GoalContribution, SavingsGoal, Transaction

User = get_user_model()
D = Decimal
TODAY = datetime.date(2026, 10, 20)


def spend(user, amount, date, method='cash', category='food'):
    return Transaction.objects.create(user=user, kind='expense', amount=D(amount), category=category,
                                      payment_method=method, date=date)


class DailySpendingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('mitu', password='x')
        cls.other = User.objects.create_user('other', password='x')

    def daily(self, year=2026, month=10):
        return services.get_daily_spending(self.user, year, month, TODAY)

    def test_one_entry_per_day_with_totals(self):
        spend(self.user, '100', datetime.date(2026, 10, 6))
        spend(self.user, '50', datetime.date(2026, 10, 6))
        spend(self.user, '30', datetime.date(2026, 10, 31))          # after TODAY (20 Oct) in these tests
        d = self.daily()
        self.assertEqual(len(d.days), 31)
        self.assertEqual(d.days[5].amount, D('150.00'))
        self.assertTrue(d.days[30].is_future)

    def test_february_and_leap_year_lengths(self):
        self.assertEqual(len(self.daily(2026, 2).days), 28)
        self.assertEqual(len(self.daily(2028, 2).days), 29)

    def test_biggest_day_and_no_spend_days(self):
        spend(self.user, '850', datetime.date(2026, 10, 6))
        spend(self.user, '850', datetime.date(2026, 10, 9))          # tie: earliest wins
        spend(self.user, '100', datetime.date(2026, 10, 12))
        d = self.daily()
        self.assertEqual(d.biggest.date, datetime.date(2026, 10, 6))
        self.assertEqual(d.no_spend_days, 20 - 3)                    # days 1..20 started, 3 had spending

    def test_shading_levels_relative_to_biggest_day(self):
        for day, amount in [(1, '1000'), (2, '750'), (3, '500'), (4, '250'), (5, '100')]:
            spend(self.user, amount, datetime.date(2026, 10, day))
        levels = [d.level for d in self.daily().days[:6]]
        self.assertEqual(levels, [4, 3, 2, 1, 1, 0])

    def test_only_this_users_expenses(self):
        spend(self.other, '999', datetime.date(2026, 10, 3))
        Transaction.objects.create(user=self.user, kind='income', amount=D('500'), category='tuition',
                                   date=datetime.date(2026, 10, 3))
        goal = SavingsGoal.objects.create(user=self.user, name='Phone', target_amount=D('1000'))
        GoalContribution.objects.create(goal=goal, amount=D('300'), date=datetime.date(2026, 10, 3))
        d = self.daily()
        self.assertFalse(d.has_data)
        self.assertIsNone(d.biggest)

    def test_one_query(self):
        for day in range(1, 21):
            spend(self.user, '10', datetime.date(2026, 10, day))
        with self.assertNumQueries(1):
            self.daily()


class CalendarWeeksTests(TestCase):
    def test_sunday_first_with_padding(self):
        user = User.objects.create_user('mitu', password='x')
        weeks = services.calendar_weeks(services.get_daily_spending(user, 2026, 10, TODAY).days)
        # 1 October 2026 is a Thursday: Sun..Wed are blank.
        self.assertEqual(weeks[0][:4], [None, None, None, None])
        self.assertEqual(weeks[0][4].date, datetime.date(2026, 10, 1))
        self.assertTrue(all(len(week) == 7 for week in weeks))
        self.assertEqual(sum(1 for week in weeks for cell in week if cell), 31)

    def test_month_starting_on_sunday_has_no_leading_blanks(self):
        user = User.objects.create_user('mitu', password='x')
        weeks = services.calendar_weeks(services.get_daily_spending(user, 2026, 2, TODAY).days)   # 1 Feb 2026 = Sunday
        self.assertEqual(weeks[0][0].date, datetime.date(2026, 2, 1))
        self.assertEqual(len(weeks), 4)


class PaymentMethodTests(TestCase):
    def test_grouped_biggest_first_with_percent(self):
        user = User.objects.create_user('mitu', password='x')
        other = User.objects.create_user('other', password='x')
        spend(user, '600', datetime.date(2026, 10, 2), 'cash')
        spend(user, '300', datetime.date(2026, 10, 3), 'bkash')
        spend(user, '100', datetime.date(2026, 10, 4), 'nagad')
        spend(user, '999', datetime.date(2026, 9, 30), 'card')        # other month
        spend(other, '999', datetime.date(2026, 10, 4), 'card')       # other user
        rows = services.get_payment_methods(user, datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.assertEqual([(r.label, r.total, r.percent) for r in rows],
                         [('Cash', D('600.00'), D('60.0')), ('bKash', D('300.00'), D('30.0')), ('Nagad', D('100.00'), D('10.0'))])

    def test_empty(self):
        user = User.objects.create_user('mitu', password='x')
        self.assertEqual(services.get_payment_methods(user, datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)), [])


class DailyChartTests(TestCase):
    def test_bars_labels_and_highlight(self):
        days = [services.DaySpend(date=datetime.date(2026, 10, d), amount=D(a), is_future=d > 20)
                for d, a in zip(range(1, 32), ['0', '500', '1000'] + ['0'] * 28)]
        chart = charts.daily_chart(services.DailySpending(days=days))
        groups = chart['groups']
        self.assertEqual(len(groups), 31)
        self.assertTrue(groups[2]['is_biggest'])
        self.assertAlmostEqual(groups[2]['h'], charts.PLOT_HEIGHT)
        self.assertEqual(groups[0]['h'], 0)
        self.assertEqual([g['label'] for g in groups if g['label']], [1, 5, 10, 15, 20, 25, 31])
        self.assertEqual(groups[1]['title'], '2 October: ৳500.00 spent')
        self.assertEqual(groups[0]['title'], '1 October: no expenses')
        self.assertEqual(groups[25]['title'], '26 October: hasn’t happened yet')


class MonthViewDailyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mitu', password='x')
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        spend(self.user, '250', self.today, 'bkash')

    def get(self, **params):
        return self.client.get(reverse('finance:stats'), {'view': 'month', **params})

    def test_bars_by_default_with_calendar_rendered_but_hidden(self):
        response = self.get()
        self.assertEqual(response.context['daily_mode'], 'bars')
        self.assertContains(response, '<div class="daily-view" data-daily-view="bars" >')
        self.assertContains(response, '<div class="daily-view" data-daily-view="calendar" hidden>')

    def test_calendar_mode_hides_bars_instead(self):
        response = self.get(daily='calendar')
        self.assertContains(response, '<div class="daily-view" data-daily-view="calendar" >')
        self.assertContains(response, '<div class="daily-view" data-daily-view="bars" hidden>')

    def test_switch_links_jump_to_the_card_without_javascript(self):
        response = self.get()
        self.assertContains(response, 'id="daily"')
        self.assertContains(response, 'data-daily="calendar" href="?view=month&amp;year=')
        self.assertContains(response, '&amp;daily=calendar#daily"')

    def test_day_links_match_their_view(self):
        response = self.get()
        day = reverse('finance:day_detail', args=[self.today.isoformat()])
        self.assertContains(response, f'href="{day}"')                      # from the bars
        self.assertContains(response, f'href="{day}?daily=calendar"')       # from the calendar

    def test_toggle_script_loaded(self):
        self.assertContains(self.get(), 'js/daily-toggle.js')

    def test_calendar_mode_and_links_keep_it(self):
        response = self.get(daily='calendar')
        self.assertEqual(response.context['daily_mode'], 'calendar')
        self.assertContains(response, 'class="calendar"')
        self.assertContains(response, '৳250.00 spent')
        self.assertContains(response, '&amp;daily=calendar">←')                # previous-month link keeps the mode
        self.assertContains(response, '<input type="hidden" name="daily" value="calendar">')

    def test_unknown_mode_falls_back_to_bars(self):
        self.assertEqual(self.get(daily='pie').context['daily_mode'], 'bars')

    def test_payment_methods_panel(self):
        response = self.get()
        self.assertContains(response, 'How you paid')
        self.assertContains(response, 'bKash')
