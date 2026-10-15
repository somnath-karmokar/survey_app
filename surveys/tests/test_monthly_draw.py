"""The Quick draw and the Monthly draw are two separate draws on /lucky-draw/.

Quick draw : every 2 surveys = 1 attempt, small prize, no winner cap.
Monthly    : 100 surveys = 1 attempt (200 = 2, ...), its own prize per country
             (10 / 10 GBP / 5 for Nigeria) and 4 winners a month per country.
             Only playable on the 1st of the month (00:00-23:59 local time).
"""
import datetime
import json
from io import StringIO
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.lucky_draw import QUICK_DRAW_NUDGE, LuckyDrawView
from surveys.models import (
    Country, CountryLuckyDrawConfig, LuckyDrawEntry, MonthlyDrawNumbers, MonthlyDrawSettlement, Survey, SurveyCategory,
    SurveyResponse, UserSurveyProgress, WalletTransaction,
)

MONTHLY = LuckyDrawEntry.DRAW_TYPE_MONTHLY
QUICK = LuckyDrawEntry.DRAW_TYPE_SURVEY

DRAW_CONFIG = {
    **settings.LUCKY_DRAW_CONFIG,
    'SURVEYS_REQUIRED': 2,
    'POLLS_REQUIRED': 5,
    'MONTHLY_SURVEYS_REQUIRED': 100,
    # Neutralised here so the tests above don't have to think about it; the
    # dedicated MonthlyDrawQuorumTests below turns it back on.
    'MONTHLY_MIN_QUALIFIERS': 0,
    # Tests never depend on the real MONTHLY_DRAW_TEST_DATE in settings.py.
    'MONTHLY_DRAW_TEST_DATE': None,
    'NUMBER_RANGE_START': 1,
    'NUMBER_RANGE_END': 21,
}


@override_settings(LUCKY_DRAW_CONFIG=DRAW_CONFIG)
class DrawTestCase(TestCase):
    """Countries + per-country config shared by the tests below.

    The Monthly draw is only playable on the 1st of the month, so every test
    here runs with "now" frozen to the 1st unless it explicitly calls
    `self.freeze(...)` to move to another day (see MonthlyDrawWindowTests).
    """

    NOW = datetime.datetime(2030, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)

    def setUp(self):
        super().setUp()
        self._mock_now = mock.patch('django.utils.timezone.now', return_value=self.NOW).start()
        self.addCleanup(mock.patch.stopall)

    def freeze(self, when):
        """Move the mocked "now" used by timezone.now()/localtime() to `when`."""
        self._mock_now.return_value = when

    @classmethod
    def setUpTestData(cls):
        def country(name, code, symbol, currency, quick, monthly, time_zone='UTC'):
            c = Country.objects.create(name=name, code=code)
            CountryLuckyDrawConfig.objects.create(
                country=c, prize_amount=quick, currency_symbol=symbol, currency_code=currency,
                monthly_prize_amount=monthly, monthly_winner_cap=4 if monthly is not None else None,
                time_zone=time_zone,
            )
            return c

        cls.uk = country('United Kingdom', 'GB', '£', 'GBP', Decimal('1.00'), Decimal('10.00'), 'Europe/London')
        cls.us = country('United States', 'US', '$', 'USD', Decimal('1.00'), Decimal('10.00'), 'America/New_York')
        cls.ng = country('Nigeria', 'NG', '$', 'USD', Decimal('0.50'), Decimal('5.00'), 'Africa/Lagos')
        # Australia has a Quick draw config but takes no part in the Monthly draw.
        cls.au = country('Australia', 'AU', '$', 'USD', Decimal('1.00'), None)
        cls.category = SurveyCategory.objects.create(name='General', country=cls.us)
        cls.survey = Survey.objects.create(name='Milestone Survey', category=cls.category)

    counter = 0

    def make_user(self, country, surveys=0):
        DrawTestCase.counter += 1
        user = get_user_model().objects.create_user(
            username=f'u{self.counter}@example.com', email=f'u{self.counter}@example.com', password='pw',
        )
        user.profile.country = country
        user.profile.save(update_fields=['country'])
        self.set_surveys(user, surveys)
        return user

    def set_surveys(self, user, count):
        UserSurveyProgress.objects.update_or_create(
            user=user, category=self.category, level=1, defaults={'completed_count': count},
        )

    def status(self, user):
        return LuckyDrawView().get_eligibility_context(user)

    def play(self, user, draw_type, win=True):
        """Play one attempt through the real page + endpoint."""
        client = self.client_class()
        client.force_login(user)
        client.get(reverse('surveys:lucky_draw'))           # seeds the board(s) in the session
        if draw_type == MONTHLY and 'lucky_draw_grid_monthly' in client.session:
            grid = client.session['lucky_draw_grid_monthly']
            winning = set(MonthlyDrawNumbers.objects.filter(country=user.profile.country).first().winning_numbers)
            wanted = [i for i, n in enumerate(grid) if (n in winning) == win] or list(range(len(grid)))
            index = wanted[0]
        else:
            grid = client.session['lucky_draw_grid']
            lucky = client.session['lucky_draw_number']
            index = grid.index(lucky) if win else (grid.index(lucky) + 1) % len(grid)
        return client.post(
            reverse('surveys:lucky_draw'),
            data=json.dumps({'index': index, 'draw_type': draw_type}),
            content_type='application/json',
        )

    def fill_monthly_winners(self, country, count, when=None):
        """Record `count` Monthly winners in `country` (this month unless `when`)."""
        for _ in range(count):
            winner = self.make_user(country)
            entry = LuckyDrawEntry.objects.create(
                user=winner, draw_type=MONTHLY, guessed_number=1, winning_number=1,
                is_winner=True, prize='$10 USD', surveys_at_play=100, polls_at_play=0,
            )
            if when:
                LuckyDrawEntry.objects.filter(pk=entry.pk).update(created_at=when)

    def make_named_monthly_winner(self, country, first_name, last_name):
        """A Monthly winner with a real name, for tests that check the winner list."""
        winner = self.make_user(country)
        winner.first_name, winner.last_name = first_name, last_name
        winner.save(update_fields=['first_name', 'last_name'])
        LuckyDrawEntry.objects.create(
            user=winner, draw_type=MONTHLY, guessed_number=1, winning_number=1,
            is_winner=True, prize='$10 USD', surveys_at_play=100, polls_at_play=0,
        )
        return winner

    def make_banked_qualifier(self, country, total_surveys):
        """A user whose milestone(s) were reached with completions dated before
        this draw's qualifying period (1 June draw: 2 May - 1 June), so they earn
        nothing for this draw and don't count toward its minimum: their old
        attempt has expired.
        """
        user = self.make_user(country, total_surveys)
        before_this_month = self.NOW.replace(day=1) - datetime.timedelta(days=31)
        SurveyResponse.objects.bulk_create([
            SurveyResponse(user=user, survey=self.survey, completed_at=before_this_month)
            for _ in range(total_surveys)
        ])
        return user

    def make_new_qualifier(self, country, total_surveys):
        """A user who newly reaches `total_surveys` (crossing a milestone) with
        completions dated within this (frozen) month, so they count toward
        THIS month's quorum.
        """
        user = self.make_user(country, total_surveys)
        SurveyResponse.objects.bulk_create([
            SurveyResponse(user=user, survey=self.survey, completed_at=self.NOW)
            for _ in range(total_surveys)
        ])
        return user


class MonthlyAttemptsTests(DrawTestCase):
    def test_100_surveys_is_one_attempt_and_200_is_two(self):
        cases = [(0, 0), (99, 0), (100, 1), (150, 1), (199, 1), (200, 2), (300, 3)]
        for surveys, attempts in cases:
            with self.subTest(surveys=surveys):
                user = self.make_user(self.uk, surveys)
                self.assertEqual(self.status(user)['monthly_plays_available'], attempts)

    def test_profile_reports_monthly_milestones_and_qualified_users(self):
        user = self.make_user(self.us, 200)
        self.make_user(self.us, 100)
        self.make_user(self.us, 99)

        self.client.force_login(user)
        response = self.client.get(reverse('surveys:user_profile'))

        stats = response.context['monthly_draw_stats']
        self.assertEqual(stats['milestones_completed'], 2)
        self.assertEqual(stats['attempts_available'], 2)
        self.assertEqual(stats['qualified_users'], 3)                 # attempts: 200 surveys = 2, 100 = 1

        dashboard_response = self.client.get(reverse('surveys:dashboard'))
        dashboard_stats = dashboard_response.context['monthly_draw_stats']
        self.assertEqual(dashboard_stats, stats)

    def test_surplus_carries_over_after_playing_an_attempt(self):
        user = self.make_user(self.uk, 200)
        self.assertEqual(self.status(user)['monthly_plays_available'], 2)

        self.play(user, MONTHLY, win=False)

        self.assertEqual(self.status(user)['monthly_plays_available'], 1)

    def test_country_without_a_monthly_prize_does_not_take_part(self):
        user = self.make_user(self.au, 500)

        status = self.status(user)

        self.assertFalse(status['monthly_available'])
        self.assertEqual(status['monthly_plays_available'], 0)
        response = self.play(user, MONTHLY)
        self.assertEqual(response.status_code, 400)
        self.assertIn('not available in your country', response.json()['error'])

    def test_needing_more_surveys_is_refused_with_a_reason(self):
        user = self.make_user(self.uk, 99)

        response = self.play(user, MONTHLY)

        self.assertEqual(response.status_code, 400)
        self.assertIn('100 surveys', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(user=user).exists())


class SeparateFromQuickDrawTests(DrawTestCase):
    def test_quick_draw_still_needs_only_two_surveys(self):
        user = self.make_user(self.uk, 2)

        status = self.status(user)

        self.assertTrue(status['survey_eligible'])
        self.assertFalse(status['monthly_eligible'])
        self.assertEqual(status['eligible_draw_types'], [QUICK])

    def test_each_draw_keeps_its_own_counter(self):
        user = self.make_user(self.uk, 100)
        before = self.status(user)
        self.assertEqual((before['survey_plays_available'], before['monthly_plays_available']), (50, 1))

        self.play(user, MONTHLY, win=False)

        after = self.status(user)
        self.assertEqual(after['monthly_plays_available'], 0)
        self.assertEqual(after['survey_plays_available'], 50)      # Quick attempts untouched

    def test_quick_draw_keeps_its_own_small_prize_and_pays_it(self):
        user = self.make_user(self.uk, 2)

        response = self.play(user, QUICK)

        self.assertTrue(response.json()['is_winner'])
        self.assertEqual(response.json()['prize'], '£1 GBP')
        self.assertEqual(user.profile.__class__.objects.get(user=user).wallet_balance, Decimal('1.00'))

    def test_quick_draw_has_no_winner_cap(self):
        for _ in range(6):                                          # more than the Monthly cap of 4
            self.assertTrue(self.play(self.make_user(self.us, 2), QUICK).json()['is_winner'])

    def test_quick_winners_do_not_use_up_the_monthly_prizes(self):
        for _ in range(4):
            LuckyDrawEntry.objects.create(
                user=self.make_user(self.us), draw_type=QUICK, guessed_number=1, winning_number=1,
                is_winner=True, prize='$1 USD', surveys_at_play=2, polls_at_play=0,
            )

        self.assertTrue(self.status(self.make_user(self.us, 100))['monthly_open'])

    def test_nudge_is_about_the_quick_draw_even_when_monthly_attempts_are_held(self):
        with override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SURVEYS_REQUIRED': 101}):
            user = self.make_user(self.uk, 100)                     # 1 Monthly attempt, 1 short of Quick

            self.assertTrue(self.status(user)['user_eligible'])      # eligible (Monthly)...
            self.assertEqual(LuckyDrawView().quick_draw_nudge(user), QUICK_DRAW_NUDGE)   # ...but not for Quick


class MonthlyPrizeTests(DrawTestCase):
    def test_uk_winner_gets_10_pounds_in_their_wallet(self):
        user = self.make_user(self.uk, 100)

        response = self.play(user, MONTHLY)

        self.assertTrue(response.json()['is_winner'])
        self.assertEqual(response.json()['prize'], '£10 GBP')
        self.assertEqual(user.profile.__class__.objects.get(user=user).wallet_balance, Decimal('10.00'))
        txn = WalletTransaction.objects.get(profile__user=user)
        self.assertEqual((txn.amount, txn.currency_code, txn.currency_symbol), (Decimal('10.00'), 'GBP', '£'))
        self.assertEqual(txn.description, 'Monthly lucky draw win')
        self.assertEqual(LuckyDrawEntry.objects.get(user=user).draw_type, MONTHLY)

    def test_us_winner_gets_10_dollars(self):
        user = self.make_user(self.us, 100)
        self.play(user, MONTHLY)
        self.assertEqual(WalletTransaction.objects.get(profile__user=user).amount, Decimal('10.00'))

    def test_nigeria_winner_gets_5_dollars(self):
        user = self.make_user(self.ng, 100)

        response = self.play(user, MONTHLY)

        self.assertEqual(response.json()['prize'], '$5 USD')
        txn = WalletTransaction.objects.get(profile__user=user)
        self.assertEqual((txn.amount, txn.currency_code), (Decimal('5.00'), 'USD'))

    def test_wrong_number_wins_nothing_but_uses_the_attempt(self):
        user = self.make_user(self.uk, 100)

        response = self.play(user, MONTHLY, win=False)

        self.assertFalse(response.json()['is_winner'])
        self.assertFalse(WalletTransaction.objects.filter(profile__user=user).exists())
        self.assertEqual(self.status(user)['monthly_plays_available'], 0)

    def test_monthly_winner_email_names_the_monthly_draw_and_the_prize(self):
        self.play(self.make_user(self.uk, 100), MONTHLY)

        winner_email = mail.outbox[0]
        self.assertEqual(winner_email.subject, 'Congratulations! You Won the Monthly Draw!')
        html = winner_email.alternatives[0][0]
        self.assertIn('you\'ve won the Monthly Draw!', html)
        self.assertIn('Prize: £10 GBP', html)


class MonthlyWinnerCapTests(DrawTestCase):
    def test_draw_stays_open_below_the_cap(self):
        self.fill_monthly_winners(self.us, 3)

        status = self.status(self.make_user(self.us, 100))

        self.assertTrue(status['monthly_open'])
        self.assertEqual((status['monthly_winners_this_month'], status['monthly_winner_cap']), (3, 4))

    def test_fifth_player_is_blocked_and_keeps_their_attempt(self):
        self.fill_monthly_winners(self.us, 4)
        latecomer = self.make_user(self.us, 100)

        response = self.play(latecomer, MONTHLY)

        self.assertEqual(response.status_code, 400)
        self.assertIn('have been won', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(user=latecomer).exists())      # nothing recorded
        status = self.status(latecomer)
        self.assertEqual(status['monthly_plays_available'], 1)                          # attempt kept
        self.assertFalse(status['monthly_open'])
        self.assertFalse(status['monthly_eligible'])

    def test_blocked_player_sees_who_won_this_months_slots(self):
        self.make_named_monthly_winner(self.us, 'John', 'Okafor')
        self.make_named_monthly_winner(self.us, 'Benson', 'Ade')
        self.fill_monthly_winners(self.us, 2)     # 2 more, unnamed, to reach the cap of 4
        latecomer = self.make_user(self.us, 100)

        response = self.play(latecomer, MONTHLY)
        error = response.json()['error']

        self.assertIn('Winners:', error)
        self.assertIn('1: J. Okafor', error)
        self.assertIn('2: B. Ade', error)

        self.client.force_login(latecomer)
        page = self.client.get(reverse('surveys:lucky_draw'))
        self.assertContains(page, 'Winners:')
        self.assertContains(page, '1: J. Okafor')

    def test_each_country_has_its_own_four_winners(self):
        self.fill_monthly_winners(self.us, 4)

        self.assertFalse(self.status(self.make_user(self.us, 100))['monthly_open'])
        self.assertTrue(self.status(self.make_user(self.uk, 100))['monthly_open'])
        self.assertTrue(self.status(self.make_user(self.ng, 100))['monthly_open'])

    def test_last_months_winners_do_not_count(self):
        last_month = timezone.now().replace(day=1) - timezone.timedelta(days=2)
        self.fill_monthly_winners(self.us, 4, when=last_month)

        self.assertTrue(self.status(self.make_user(self.us, 100))['monthly_open'])

    def test_cap_is_reached_by_playing_not_just_by_seeded_rows(self):
        winners = [self.make_user(self.us, 100) for _ in range(4)]
        for user in winners:
            self.assertTrue(self.play(user, MONTHLY).json()['is_winner'])
        fifth = self.make_user(self.us, 100)

        self.assertEqual(self.play(fifth, MONTHLY).status_code, 400)
        self.assertEqual(LuckyDrawEntry.objects.filter(draw_type=MONTHLY, is_winner=True).count(), 4)


class MonthlyDrawPageTests(DrawTestCase):
    def get_page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('surveys:lucky_draw'))

    def test_panel_shows_attempts_progress_prize_and_winners(self):
        self.fill_monthly_winners(self.us, 1)
        page = self.get_page(self.make_user(self.us, 250))

        self.assertContains(page, 'Monthly Draw')
        self.assertContains(page, 'Every 100 surveys you complete earns one Monthly draw attempt')
        self.assertContains(page, '$10 USD')
        self.assertContains(page, '50/100 surveys')                # 250 surveys = 2 attempts + 50 toward the next
        self.assertContains(page, '1 of 4 prizes claimed this month')
        self.assertEqual(page.context['monthly_plays_available'], 2)

    def test_closed_month_explains_when_it_reopens(self):
        self.fill_monthly_winners(self.us, 4)
        page = self.get_page(self.make_user(self.us, 100))

        self.assertContains(page, "All of this month")
        self.assertContains(page, 'opens again on')
        self.assertNotContains(page, 'will be waiting')                  # attempts don't carry over
        self.assertNotIn('kept for next month', self.play(self.make_user(self.us, 100), MONTHLY).json()['error'])

    def test_country_outside_the_monthly_draw_sees_no_panel(self):
        page = self.get_page(self.make_user(self.au, 500))

        self.assertNotContains(page, 'id="monthly-draw-panel"')


class MonthlyDrawWindowTests(DrawTestCase):
    """The Monthly draw only runs on the 1st of the month, 00:00-23:59 local time."""

    def test_eligible_on_the_1st_but_not_on_other_days(self):
        user = self.make_user(self.uk, 100)
        self.assertTrue(self.status(user)['monthly_eligible'])          # NOW is the 1st

        self.freeze(self.NOW.replace(day=15))
        status = self.status(user)
        self.assertTrue(status['monthly_open'])                        # cap isn't the reason
        self.assertFalse(status['monthly_window_open'])
        self.assertFalse(status['monthly_eligible'])

        self.freeze(self.NOW.replace(month=self.NOW.month + 1, day=1))
        self.assertTrue(self.status(user)['monthly_eligible'])          # open again on the next 1st

    def test_play_is_refused_outside_the_window_and_attempt_is_kept(self):
        user = self.make_user(self.uk, 100)
        self.freeze(self.NOW.replace(day=15))

        response = self.play(user, MONTHLY)

        self.assertEqual(response.status_code, 400)
        self.assertIn('only runs on the 1st', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(user=user).exists())
        self.assertEqual(self.status(user)['monthly_plays_available'], 1)

    def test_page_explains_the_window_is_closed(self):
        user = self.make_user(self.uk, 100)
        self.freeze(self.NOW.replace(day=15))
        self.client.force_login(user)

        page = self.client.get(reverse('surveys:lucky_draw'))

        self.assertContains(page, 'only runs on the 1st')
        self.assertContains(page, 'opens again on')


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5})
class MonthlyDrawQuorumTests(DrawTestCase):
    """At least MONTHLY_MIN_QUALIFIERS people must newly cross the Monthly
    milestone in a country during the current month before that country's
    Monthly draw runs at all this cycle — regardless of anyone's banked
    attempts from earlier months.
    """

    def test_below_minimum_blocks_the_whole_countrys_draw(self):
        for _ in range(4):
            self.make_new_qualifier(self.us, 100)
        bystander = self.make_user(self.us, 0)      # hasn't reached the milestone themselves

        status = self.status(bystander)

        self.assertEqual(status['monthly_milestone_qualifiers'], 4)
        self.assertFalse(status['monthly_quorum_met'])
        self.assertFalse(status['monthly_eligible'])

    def test_reaching_the_minimum_opens_the_draw(self):
        for _ in range(5):
            self.make_new_qualifier(self.us, 100)

        status = self.status(self.make_user(self.us, 0))

        self.assertEqual(status['monthly_milestone_qualifiers'], 5)
        self.assertTrue(status['monthly_quorum_met'])

    def test_attempts_from_before_this_draws_period_do_not_count_toward_quorum(self):
        for _ in range(3):
            self.make_new_qualifier(self.us, 100)                      # 3 attempts this cycle...
        blocked_player = self.make_new_qualifier(self.us, 100)         # ...plus this player's = 4
        self.make_banked_qualifier(self.us, 100)                       # earlier period: expired, not counted

        self.assertEqual(self.status(blocked_player)['monthly_plays_available'], 1)
        self.assertFalse(self.status(blocked_player)['monthly_quorum_met'])

        response = self.play(blocked_player, MONTHLY)

        self.assertEqual(response.status_code, 400)
        self.assertIn('Not enough people have reached the 100-survey milestone', response.json()['error'])
        self.assertIn('(at least 5 users needed for monthly surveys to run)', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(user=blocked_player).exists())
        self.assertEqual(self.status(blocked_player)['monthly_plays_available'], 1)     # attempt kept

    def test_page_explains_the_quorum_is_not_met(self):
        for _ in range(3):
            self.make_new_qualifier(self.us, 100)
        user = self.make_new_qualifier(self.us, 100)                   # 4 attempts in all
        self.client.force_login(user)

        page = self.client.get(reverse('surveys:lucky_draw'))

        self.assertContains(page, 'Not enough people have reached the 100-survey milestone')
        self.assertContains(page, 'at least 5 users needed for monthly surveys to run')

    def test_other_countries_are_unaffected_by_one_countrys_shortfall(self):
        for _ in range(4):
            self.make_new_qualifier(self.us, 100)                      # US: below quorum
        for _ in range(5):
            self.make_new_qualifier(self.uk, 100)                      # UK: meets quorum

        self.assertFalse(self.status(self.make_user(self.us, 0))['monthly_quorum_met'])
        self.assertTrue(self.status(self.make_user(self.uk, 0))['monthly_quorum_met'])


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_DRAW_TEST_DATE': None})
class MonthlyDrawTimeZoneTests(DrawTestCase):
    """The Monthly draw opens at 00:00 on the 1st on each country's own clock."""

    def utc(self, *args):
        return datetime.datetime(*args, tzinfo=datetime.timezone.utc)

    def window_open(self, user, at):
        self.freeze(at)
        return self.status(user)['monthly_window_open']

    def test_opens_at_local_midnight_and_closes_at_local_2359(self):
        cases = [
            # country, one minute before local 00:00 on 1 Jul, local 00:00 1 Jul, local 23:59 1 Jul, local 00:00 2 Jul
            (self.uk, self.utc(2030, 6, 30, 22, 59), self.utc(2030, 6, 30, 23, 0),     # London BST = UTC+1
             self.utc(2030, 7, 1, 22, 59), self.utc(2030, 7, 1, 23, 0)),
            (self.ng, self.utc(2030, 6, 30, 22, 59), self.utc(2030, 6, 30, 23, 0),     # Lagos = UTC+1
             self.utc(2030, 7, 1, 22, 59), self.utc(2030, 7, 1, 23, 0)),
            (self.us, self.utc(2030, 7, 1, 3, 59), self.utc(2030, 7, 1, 4, 0),         # New York EDT = UTC-4
             self.utc(2030, 7, 2, 3, 59), self.utc(2030, 7, 2, 4, 0)),
        ]
        for country, before, midnight, last_minute, next_day in cases:
            with self.subTest(country=country.code):
                user = self.make_user(country, 100)
                self.assertFalse(self.window_open(user, before))
                self.assertTrue(self.window_open(user, midnight))
                self.assertTrue(self.window_open(user, last_minute))
                self.assertFalse(self.window_open(user, next_day))

    def test_playing_just_after_local_midnight_works(self):
        user = self.make_user(self.ng, 100)
        self.freeze(self.utc(2030, 6, 30, 23, 5))                      # 00:05 on 1 Jul in Lagos

        response = self.play(user, MONTHLY)

        self.assertEqual(response.status_code, 200)

    def test_win_just_after_local_midnight_counts_toward_the_new_month(self):
        self.freeze(self.utc(2030, 6, 30, 23, 30))                     # 00:30 on 1 Jul in Lagos, still June in UTC
        self.fill_monthly_winners(self.ng, 1)

        self.freeze(self.utc(2030, 7, 1, 12, 0))
        self.assertEqual(self.status(self.make_user(self.ng, 100))['monthly_winners_this_month'], 1)

    def test_reopen_date_is_the_local_1st(self):
        self.freeze(self.utc(2030, 7, 15, 12, 0))

        status = self.status(self.make_user(self.ng, 100))

        self.assertEqual(status['monthly_resets_on'], datetime.date(2030, 8, 1))
        self.assertIn('August 1', self.play(self.make_user(self.ng, 100), MONTHLY).json()['error'])


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': False})
class MonthlyDrawBoardTests(DrawTestCase):
    """The Monthly draw board is numbered 1 to N, N = users in the country who reached the milestone."""

    def load_page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('surveys:lucky_draw'))

    def test_board_is_1_to_n_milestone_users(self):
        player = self.make_user(self.uk, 100)
        for _ in range(4):
            self.make_user(self.uk, 150)
        self.make_user(self.uk, 99)                                     # not at the milestone
        self.make_user(self.us, 300)                                    # other country

        page = self.load_page(player)

        self.assertEqual(sorted(self.client.session['lucky_draw_grid_monthly']), [1, 2, 3, 4, 5])
        winning = MonthlyDrawNumbers.objects.get(country=self.uk).winning_numbers
        self.assertEqual(len(winning), 4)
        self.assertTrue(set(winning) <= {1, 2, 3, 4, 5})
        self.assertEqual(len(page.context['monthly_grid_range']), 5)
        self.assertEqual(sorted(self.client.session['lucky_draw_grid']), list(range(1, 22)))   # Quick board unchanged
        self.assertNotContains(page, '<span class="number-placeholder">3</span>')              # numbers stay hidden

    def test_monthly_play_uses_the_monthly_board(self):
        player = self.make_user(self.uk, 100)
        for _ in range(2):
            self.make_user(self.uk, 100)

        result = self.play(player, MONTHLY, win=True).json()

        self.assertTrue(result['is_winner'])
        self.assertIn(result['guessed_number'], (1, 2, 3))
        self.assertEqual(LuckyDrawEntry.objects.get(user=player).draw_type, MONTHLY)

    def test_quick_play_still_uses_the_quick_board(self):
        player = self.make_user(self.uk, 100)
        for _ in range(2):
            self.make_user(self.uk, 100)

        self.assertTrue(self.play(player, QUICK, win=True).json()['is_winner'])

    def test_playing_clears_both_boards(self):
        player = self.make_user(self.uk, 100)
        self.make_user(self.uk, 100)
        client = self.client_class()
        client.force_login(player)
        client.get(reverse('surveys:lucky_draw'))
        grid = client.session['lucky_draw_grid_monthly']
        client.post(reverse('surveys:lucky_draw'), data=json.dumps({'index': 0, 'draw_type': MONTHLY}),
                    content_type='application/json')

        for key in ('lucky_draw_grid', 'lucky_draw_number', 'lucky_draw_grid_monthly', 'lucky_draw_number_monthly'):
            self.assertNotIn(key, client.session)

    def test_fewer_than_two_milestone_users_falls_back_to_the_normal_board(self):
        player = self.make_user(self.uk, 100)                           # the only one

        page = self.load_page(player)

        self.assertNotIn('lucky_draw_grid_monthly', self.client.session)
        self.assertEqual(len(page.context['monthly_grid_range']), 0)
        self.assertTrue(self.play(player, MONTHLY, win=True).json()['is_winner'])


class NoDrawAvailablePageTests(DrawTestCase):
    def test_no_board_when_no_draw_is_available(self):
        user = self.make_user(self.uk, 1)                               # 1 survey: no Quick, Poll or Monthly play
        self.client.force_login(user)

        page = self.client.get(reverse('surveys:lucky_draw'))

        self.assertFalse(page.context['user_eligible'])
        self.assertNotContains(page, 'class="number-box')
        self.assertNotContains(page, 'id="number-grid"')
        self.assertNotContains(page, 'TESTING MODE')
        self.assertContains(page, 'You need to complete 2 surveys')     # the explanation is still shown

    def test_board_shown_when_a_draw_is_available(self):
        self.client.force_login(self.make_user(self.uk, 2))

        page = self.client.get(reverse('surveys:lucky_draw'))

        self.assertContains(page, 'id="number-grid"')
        self.assertContains(page, 'class="number-box')


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': False})
class MonthlySharedNumbersTests(DrawTestCase):
    """Each country has 4 winning numbers a month, shown on the page; a picked number is blocked for everyone."""

    def setUp(self):
        super().setUp()
        self.players = [self.make_user(self.uk, 100) for _ in range(8)]           # board 1-8

    def open_board(self, user):
        client = self.client_class()
        client.force_login(user)
        page = client.get(reverse('surveys:lucky_draw'))
        return client, page

    def pick(self, client, number):
        index = client.session['lucky_draw_grid_monthly'].index(number)
        return client.post(reverse('surveys:lucky_draw'), data=json.dumps({'index': index, 'draw_type': MONTHLY}),
                           content_type='application/json')

    def winning(self):
        return MonthlyDrawNumbers.objects.get(country=self.uk).winning_numbers

    def losing_number(self):
        return next(n for n in range(1, 9) if n not in self.winning())

    def test_four_winning_numbers_are_drawn_once_and_shown_to_every_player(self):
        _client, first_page = self.open_board(self.players[0])
        _client, second_page = self.open_board(self.players[1])

        self.assertEqual(MonthlyDrawNumbers.objects.filter(country=self.uk).count(), 1)
        self.assertEqual(len(self.winning()), 4)
        shown = [item['number'] for item in second_page.context['monthly_winning_numbers']]
        self.assertEqual(shown, self.winning())
        self.assertContains(first_page, 'id="monthly-winning-numbers"')

    def test_other_countries_get_their_own_numbers(self):
        for _ in range(8):
            self.make_user(self.us, 100)
        self.open_board(self.players[0])
        self.open_board(self.make_user(self.us, 100))

        self.assertEqual(MonthlyDrawNumbers.objects.count(), 2)

    def test_a_picked_number_is_blocked_for_the_next_player(self):
        client, _page = self.open_board(self.players[0])
        number = self.losing_number()
        self.assertFalse(self.pick(client, number).json()['is_winner'])

        next_client, page = self.open_board(self.players[1])

        self.assertNotIn(number, next_client.session['lucky_draw_grid_monthly'])
        self.assertEqual([t['number'] for t in page.context['monthly_taken_numbers']], [number])
        self.assertContains(page, 'monthly-taken-box')

    def test_two_players_cannot_take_the_same_number(self):
        first, _ = self.open_board(self.players[0])
        second, _ = self.open_board(self.players[1])
        number = self.losing_number()

        self.assertEqual(self.pick(first, number).status_code, 200)
        response = self.pick(second, number)

        self.assertEqual(response.status_code, 409)
        self.assertIn('just been picked', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(user=self.players[1]).exists())
        self.assertEqual(self.status(self.players[1])['monthly_plays_available'], 1)    # attempt kept

    def test_finding_a_winning_number_wins_and_marks_it_won(self):
        client, _ = self.open_board(self.players[0])
        number = self.winning()[0]

        result = self.pick(client, number).json()

        self.assertTrue(result['is_winner'])
        self.assertEqual(result['winning_numbers'], self.winning())
        _next, page = self.open_board(self.players[1])
        won = {item['number']: item['won_by'] for item in page.context['monthly_winning_numbers']}
        self.assertTrue(won[number])
        self.assertEqual(sum(1 for name in won.values() if name), 1)

    def test_draw_closes_once_all_four_winning_numbers_are_found(self):
        self.open_board(self.players[0])                                            # draws the numbers
        for player, number in zip(self.players, self.winning()):
            client, _ = self.open_board(player)
            self.assertTrue(self.pick(client, number).json()['is_winner'])

        status = self.status(self.players[5])
        self.assertFalse(status['monthly_open'])
        self.assertIn('have been won', self.play(self.players[5], MONTHLY).json()['error'])


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': False})
class MonthlyBoardSizeThisMonthTests(DrawTestCase):
    """N (board size, and range of the 4 winning numbers) = users who reached the milestone this month."""

    def open_board(self, user):
        client = self.client_class()
        client.force_login(user)
        client.get(reverse('surveys:lucky_draw'))
        return client

    def test_only_this_months_milestone_users_count(self):
        player = self.make_new_qualifier(self.uk, 100)
        for _ in range(5):
            self.make_new_qualifier(self.uk, 100)                      # 6 this month in total
        for _ in range(3):
            self.make_banked_qualifier(self.uk, 100)                   # reached it last month: not counted

        client = self.open_board(player)

        self.assertEqual(sorted(client.session['lucky_draw_grid_monthly']), [1, 2, 3, 4, 5, 6])
        winning = MonthlyDrawNumbers.objects.get(country=self.uk).winning_numbers
        self.assertEqual(len(winning), 4)
        self.assertTrue(all(1 <= n <= 6 for n in winning))

    def test_out_of_range_numbers_are_redrawn_while_nobody_has_picked(self):
        player = self.make_new_qualifier(self.uk, 100)
        for _ in range(4):
            self.make_new_qualifier(self.uk, 100)                      # N = 5
        MonthlyDrawNumbers.objects.create(country=self.uk, year=2030, month=6, winning_numbers=[2, 9, 14, 20])

        self.open_board(player)

        winning = MonthlyDrawNumbers.objects.get(country=self.uk).winning_numbers
        self.assertTrue(all(1 <= n <= 5 for n in winning))


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5, 'MONTHLY_DRAW_TEST_DATE': None})
class MonthlyNoDrawPayoutTests(DrawTestCase):
    """When too few qualify for the draw to run, attempt holders are paid the Monthly prize."""

    def setUp(self):
        super().setUp()
        self.holders = [self.make_new_qualifier(self.uk, 100) for _ in range(3)]       # 3 of 5: no draw
        self.next_day = self.NOW + datetime.timedelta(days=1)

    def settle(self):
        LuckyDrawView().settle_due_monthly_draws(CountryLuckyDrawConfig.objects.get(country=self.uk))

    def wallet(self, user):
        return user.profile.__class__.objects.get(user=user).wallet_balance

    def test_message_promises_the_prize_on_the_draw_day(self):
        response = self.play(self.holders[0], MONTHLY)

        self.assertIn('at least 5 users needed', response.json()['error'])
        self.assertIn('Your £10 will be automatically added to your wallet', response.json()['error'])
        self.client.force_login(self.holders[0])
        self.assertContains(self.client.get(reverse('surveys:lucky_draw')),
                            'Your £10 will be automatically added to your wallet')

    def test_nothing_is_paid_while_the_draw_day_is_still_running(self):
        self.settle()

        self.assertEqual(self.wallet(self.holders[0]), Decimal('0.00'))
        self.assertFalse(MonthlyDrawSettlement.objects.filter(draw_date=self.NOW.date()).exists())

    def test_attempt_holders_are_paid_once_the_day_ends(self):
        self.freeze(self.next_day)

        self.settle()
        self.settle()                                                   # running again pays nothing more

        for user in self.holders:
            self.assertEqual(self.wallet(user), Decimal('10.00'))
            txn = WalletTransaction.objects.get(profile__user=user)
            self.assertEqual((txn.amount, txn.currency_code), (Decimal('10.00'), 'GBP'))
            self.assertEqual(self.status(user)['monthly_plays_available'], 0)    # attempt used up
        settlement = MonthlyDrawSettlement.objects.get(country=self.uk, draw_date=self.NOW.date())
        self.assertEqual((settlement.quorum_met, settlement.qualifiers, settlement.paid_users), (False, 3, 3))

    def test_people_without_an_attempt_are_not_paid(self):
        nobody = self.make_new_qualifier(self.uk, 40)
        self.freeze(self.next_day)

        self.settle()

        self.assertEqual(self.wallet(nobody), Decimal('0.00'))

    def test_other_countries_are_settled_on_their_own(self):
        for _ in range(5):
            self.make_new_qualifier(self.us, 100)                       # US meets the minimum
        self.freeze(self.next_day + datetime.timedelta(hours=6))        # past the 1st in New York too

        call_command('settle_monthly_draws', stdout=StringIO())

        us = MonthlyDrawSettlement.objects.get(country=self.us, draw_date=self.NOW.date())
        self.assertTrue(us.quorum_met)
        self.assertEqual(us.paid_users, 0)
        self.assertEqual(MonthlyDrawSettlement.objects.get(country=self.uk, draw_date=self.NOW.date()).paid_users, 3)

    def test_opening_the_draw_page_settles_as_a_backup(self):
        self.freeze(self.next_day)
        self.client.force_login(self.holders[0])

        self.client.get(reverse('surveys:lucky_draw'))

        self.assertEqual(self.wallet(self.holders[0]), Decimal('10.00'))

    def test_payout_does_not_use_up_next_months_prizes(self):
        self.freeze(self.utc_for(2030, 7, 1, 12))                       # settled late, on the next draw day
        self.settle()

        self.assertEqual(self.status(self.make_user(self.uk, 100))['monthly_winners_this_month'], 0)

    def utc_for(self, *args):
        return datetime.datetime(*args, tzinfo=datetime.timezone.utc)


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': True})
class TestingBannerTests(DrawTestCase):
    def page_for(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('surveys:lucky_draw'))

    def test_monthly_tab_does_not_show_the_quick_winning_number(self):
        player = self.make_user(self.uk, 100)
        for _ in range(4):
            self.make_user(self.uk, 100)
        LuckyDrawEntry.objects.create(                                  # Quick plays used up: Monthly is selected
            user=player, draw_type=QUICK, guessed_number=1, winning_number=2,
            is_winner=False, surveys_at_play=100, polls_at_play=0,
        )

        page = self.page_for(player)

        self.assertEqual(page.context['selected_draw_type'], MONTHLY)
        self.assertContains(page, '<span id="testing-quick-winning" class="d-none">')
        self.assertContains(page, '<span id="testing-monthly-winning" class="">')

    def test_quick_tab_still_shows_its_winning_number(self):
        page = self.page_for(self.make_user(self.uk, 2))

        self.assertEqual(page.context['selected_draw_type'], QUICK)
        self.assertContains(page, '<span id="testing-quick-winning" class="">')



@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5, 'MONTHLY_DRAW_TEST_DATE': None})
class MonthlyDrawRequirementTests(DrawTestCase):
    """The agreed behaviour, end to end:
    fewer than 5 qualify -> no draw, the message below, and qualifying users are paid the prize;
    5 or more qualify   -> they can play the Monthly draw.
    """
    MESSAGE = (
        "Not enough people have reached the 100-survey milestone in your country this month yet "
        "(at least 5 users needed for monthly surveys to run) — there's no monthly draw this cycle. "
        "Your $10 will be automatically added to your wallet"
    )

    def test_fewer_than_five_no_draw_message_and_payout(self):
        users = [self.make_new_qualifier(self.us, 100) for _ in range(4)]

        status = self.status(users[0])
        self.assertFalse(status['monthly_eligible'])                                   # no draw
        self.assertEqual(self.play(users[0], MONTHLY).json()['error'], self.MESSAGE)  # exact message
        self.client.force_login(users[0])
        self.assertContains(self.client.get(reverse('surveys:lucky_draw')), 'Your $10 will be automatically added')

        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))                    # draw day over in New York
        call_command('settle_monthly_draws', stdout=StringIO())

        for user in users:
            txn = WalletTransaction.objects.get(profile__user=user)
            self.assertEqual((txn.amount, txn.currency_code), (Decimal('10.00'), 'USD'))

    def test_five_or_more_can_play(self):
        users = [self.make_new_qualifier(self.us, 100) for _ in range(5)]

        self.assertTrue(self.status(users[0])['monthly_eligible'])
        self.assertEqual(self.play(users[0], MONTHLY).status_code, 200)

        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))
        call_command('settle_monthly_draws', stdout=StringIO())
        self.assertFalse(WalletTransaction.objects.filter(
            profile__user=users[1], description__startswith='Monthly draw prize - draw did not run',
        ).exists())                                                                    # no automatic payout


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5, 'MONTHLY_DRAW_TEST_DATE': None})
class SettlementFromTrafficTests(DrawTestCase):
    """No cron job: any page visit settles ended draw days, at most every 10 minutes."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.holders = [self.make_new_qualifier(self.us, 100) for _ in range(3)]       # 3 of 5: no draw

    def wallet(self, user):
        return user.profile.__class__.objects.get(user=user).wallet_balance

    def test_any_visit_after_the_draw_day_pays_out(self):
        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))                    # past the 1st in New York

        self.client.get(reverse('surveys:home'))                                       # an anonymous visitor

        for user in self.holders:
            self.assertEqual(self.wallet(user), Decimal('10.00'))

    def test_checks_at_most_every_ten_minutes(self):
        self.client.get(reverse('surveys:home'))                                       # still the draw day: checked, nothing due
        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))

        self.client.get(reverse('surveys:home'))                                       # within 10 minutes of the last check
        self.assertEqual(self.wallet(self.holders[0]), Decimal('0.00'))

        from django.core.cache import cache
        cache.clear()                                                                  # the 10 minutes have passed
        self.client.get(reverse('surveys:home'))
        self.assertEqual(self.wallet(self.holders[0]), Decimal('10.00'))

    def test_a_failure_never_breaks_the_page(self):
        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))
        with mock.patch('surveys.lucky_draw.LuckyDrawView.settle_due_monthly_draws', side_effect=RuntimeError('boom')), \
                self.assertLogs('surveys.middleware', level='ERROR'):
            response = self.client.get(reverse('surveys:home'))

        self.assertEqual(response.status_code, 200)

    def test_does_nothing_outside_the_days_after_the_draw(self):
        self.freeze(self.NOW.replace(day=10))                                          # June 10: outside the window

        self.client.get(reverse('surveys:home'))

        self.assertEqual(self.wallet(self.holders[0]), Decimal('0.00'))
        self.assertFalse(MonthlyDrawSettlement.objects.exists())

    def test_runs_in_the_days_after_the_test_date(self):
        with override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5,
                                                  'MONTHLY_DRAW_TEST_DATE': '2030-06-15'}):
            from surveys.middleware import MonthlyDrawSettlementMiddleware
            window = MonthlyDrawSettlementMiddleware(lambda request: None).in_settlement_window
            for day, expected in ((14, False), (15, True), (18, True), (19, False)):
                self.freeze(self.NOW.replace(day=day))
                self.assertEqual(window(), expected, f'June {day}')


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': False})
class SeparateResultsTests(DrawTestCase):
    """A draw's results are only shown with that draw: no Quick results beside the Monthly draw."""

    def page_for(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('surveys:lucky_draw')).content.decode()

    def monthly_panel(self, html):
        start = html.index('id="monthly-draw-panel"')
        return html[start:html.index('</div>\n                    </div>', start)]

    def test_lost_quick_play_is_labelled_and_kept_out_of_the_monthly_panel(self):
        user = self.make_user(self.uk, 2)
        self.play(user, QUICK, win=False)                               # Quick lost; nothing left to play

        html = self.page_for(user)

        self.assertIn('Your last Quick draw:', html)
        self.assertNotIn('lucky number was', self.monthly_panel(html))
        self.assertNotIn('Your last Quick draw', self.monthly_panel(html))

    def test_monthly_result_shows_in_the_monthly_panel_with_monthly_wording(self):
        player = self.make_user(self.uk, 100)
        for _ in range(7):
            self.make_user(self.uk, 100)                                # board 1-8, so a losing number exists
        self.play(player, MONTHLY, win=False)
        self.play(player, QUICK, win=False)                             # use up Quick plays too
        LuckyDrawEntry.objects.filter(user=player, draw_type=QUICK).update(surveys_at_play=100)

        panel = self.monthly_panel(self.page_for(player))

        self.assertIn('Your last Monthly draw', panel)
        self.assertIn("which wasn't a winning number", panel)

    def test_no_draw_payout_reads_as_a_payout_not_lucky_number_zero(self):
        player = self.make_user(self.uk, 100)
        LuckyDrawEntry.objects.create(user=player, draw_type=MONTHLY, guessed_number=0, winning_number=0,
                                      is_winner=True, prize='£10 GBP (no draw)', surveys_at_play=100, polls_at_play=0)

        html = self.page_for(player)

        self.assertIn("the draw didn't run, so your £10 GBP was added to your wallet", html)
        self.assertNotIn('lucky number 0', html)

    def test_plays_left_after_a_monthly_play_counts_only_monthly_attempts(self):
        player = self.make_user(self.uk, 200)                           # 2 Monthly attempts, 100 Quick plays
        self.make_user(self.uk, 200)

        result = self.play(player, MONTHLY, win=False).json()

        self.assertEqual(result['draw_plays_remaining'], 1)
        self.assertGreater(result['plays_remaining'], 1)                # overall total still drives Play Again


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': True, 'POLLS_REQUIRED': 1,
                                      'MONTHLY_DRAW_TEST_DATE': None})
class DrawTabsLayoutTests(DrawTestCase):
    """Tabs come first; the Monthly panel belongs to the Monthly tab only."""

    def page_for(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('surveys:lucky_draw'))

    def panel_tag(self, html):
        start = html.index('<div class="card border-warning')
        return html[start:html.index('>', start)]

    def poll_player_with_closed_monthly(self):
        from surveys.models import Poll, PollResponse
        self.freeze(self.NOW.replace(day=15))                           # not a draw day
        user = self.make_user(self.uk, 100)                             # 1 Monthly attempt held
        LuckyDrawEntry.objects.create(user=user, draw_type=QUICK, guessed_number=1, winning_number=2,
                                      is_winner=False, surveys_at_play=100, polls_at_play=0)   # no Quick plays
        PollResponse.objects.create(user=user, poll=Poll.objects.create(title='P', country=self.uk))
        return user

    def test_screenshot_case_poll_selected_monthly_closed(self):
        page = self.page_for(self.poll_player_with_closed_monthly())
        html = page.content.decode()

        self.assertEqual(page.context['selected_draw_type'], 'poll')
        self.assertLess(html.index('draw-type-btn'), html.index('id="monthly-draw-panel"'))   # tabs first
        self.assertIn('d-none', self.panel_tag(html))                                        # panel hidden on Poll tab
        monthly_tab = html[html.index('data-draw-type="monthly"'):html.index('</button>', html.index('data-draw-type="monthly"'))]
        self.assertNotIn('disabled', monthly_tab)                                            # can click to see why
        self.assertIn('Closed', monthly_tab)
        self.assertNotIn('will be waiting', html)

    def test_monthly_selected_shows_its_panel(self):
        player = self.make_user(self.uk, 100)
        for _ in range(4):
            self.make_user(self.uk, 100)
        LuckyDrawEntry.objects.create(user=player, draw_type=QUICK, guessed_number=1, winning_number=2,
                                      is_winner=False, surveys_at_play=100, polls_at_play=0)
        page = self.page_for(player)

        self.assertEqual(page.context['selected_draw_type'], MONTHLY)
        self.assertNotIn('d-none', self.panel_tag(page.content.decode()))

    def test_nothing_playable_shows_the_monthly_panel_without_tabs(self):
        self.freeze(self.NOW.replace(day=15))
        user = self.make_user(self.uk, 100)
        LuckyDrawEntry.objects.create(user=user, draw_type=QUICK, guessed_number=1, winning_number=2,
                                      is_winner=False, surveys_at_play=100, polls_at_play=0)
        html = self.page_for(user).content.decode()

        self.assertNotIn('draw-type-btn"', html.split('<script>')[0])
        self.assertNotIn('d-none', self.panel_tag(html))
        self.assertIn('only runs on the 1st of each month. It opens again on July 1.', html)

    def test_no_closed_label_on_the_draw_day_even_if_this_user_cannot_play(self):
        from surveys.models import Poll, PollResponse
        user = self.make_user(self.uk, 0)                               # draw day (NOW is the 1st), no attempt
        PollResponse.objects.create(user=user, poll=Poll.objects.create(title='P', country=self.uk))
        html = self.page_for(user).content.decode()

        start = html.index('data-draw-type="monthly"')
        monthly_tab = html[start:html.index('</button>', start)]
        self.assertNotIn('Closed', monthly_tab)
        self.assertNotIn('disabled', monthly_tab)


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_SURVEYS_REQUIRED': 100, 'MONTHLY_MIN_QUALIFIERS': 5,
                                      'MONTHLY_DRAW_TEST_DATE': None, 'SHOW_NUMBERS_FOR_TESTING': False})
class MonthlyDrawRequirementExamplesTests(DrawTestCase):
    """The written requirement's examples, with the real 1 November 2026 draw (New York time).

    O Gbenga 200 surveys, B Johnson 200, J Bloggs 100 in October.
    """
    NOW = datetime.datetime(2026, 11, 1, 15, 0, tzinfo=datetime.timezone.utc)          # 1 Nov, 10:00 New York

    def surveyed(self, name, count, day):
        """A US user who completed `count` surveys on `day` (October 2026)."""
        user = self.make_user(self.us, count)
        user.first_name, user.last_name = name.split()
        user.save(update_fields=['first_name', 'last_name'])
        when = datetime.datetime(2026, 10, day, 15, 0, tzinfo=datetime.timezone.utc)
        SurveyResponse.objects.bulk_create([SurveyResponse(user=user, survey=self.survey, completed_at=when)
                                            for _ in range(count)])
        return user

    def wallet(self, user):
        return user.profile.__class__.objects.get(user=user).wallet_balance

    def pick(self, user, number):
        client = self.client_class()
        client.force_login(get_user_model().objects.get(pk=user.pk))   # fresh, like a real login
        client.get(reverse('surveys:lucky_draw'))
        index = client.session['lucky_draw_grid_monthly'].index(number)
        return client.post(reverse('surveys:lucky_draw'), data=json.dumps({'index': index, 'draw_type': MONTHLY}),
                           content_type='application/json').json()

    def test_october_surveys_count_and_200_surveys_is_2_attempts(self):
        gbenga = self.surveyed('O Gbenga', 200, 15)
        self.surveyed('B Johnson', 200, 20)
        self.surveyed('J Bloggs', 100, 25)

        status = self.status(gbenga)

        self.assertTrue(status['monthly_window_open'])
        self.assertEqual(status['monthly_plays_available'], 2)
        self.assertEqual(status['monthly_milestone_qualifiers'], 5)              # 2 + 2 + 1 attempts
        self.assertTrue(status['monthly_eligible'])                             # 5 = draw runs
        client = self.client_class()
        client.force_login(gbenga)
        client.get(reverse('surveys:lucky_draw'))
        self.assertEqual(sorted(client.session['lucky_draw_grid_monthly']), [1, 2, 3, 4, 5])

    def test_three_attempts_no_draw_message_shows_own_total_and_pays_per_attempt(self):
        gbenga = self.surveyed('O Gbenga', 200, 15)
        bloggs = self.surveyed('J Bloggs', 100, 25)

        self.assertIn('Your $20 will be automatically added to your wallet', self.play(gbenga, MONTHLY).json()['error'])
        self.assertIn('Your $10 will be automatically added to your wallet', self.play(bloggs, MONTHLY).json()['error'])
        self.client.force_login(gbenga)
        self.assertContains(self.client.get(reverse('surveys:lucky_draw')), 'id="monthly-draw-panel"')   # console shown

        self.freeze(datetime.datetime(2026, 11, 2, 6, 0, tzinfo=datetime.timezone.utc))   # 1 Nov over in New York
        LuckyDrawView().settle_due_monthly_draws(CountryLuckyDrawConfig.objects.get(country=self.us))

        self.assertEqual(self.wallet(gbenga), Decimal('20.00'))
        self.assertEqual(self.wallet(bloggs), Decimal('10.00'))
        self.assertEqual(WalletTransaction.objects.filter(profile__user=gbenga).count(), 2)

    def test_first_come_two_players_win_twice_each(self):
        gbenga = self.surveyed('O Gbenga', 200, 15)
        johnson = self.surveyed('B Johnson', 200, 20)
        bloggs = self.surveyed('J Bloggs', 100, 25)
        self.client.force_login(gbenga)
        self.client.get(reverse('surveys:lucky_draw'))                           # draws the 4 winning numbers
        winning = MonthlyDrawNumbers.objects.get(country=self.us).winning_numbers

        results = [self.pick(gbenga, winning[0]), self.pick(gbenga, winning[1]),
                   self.pick(johnson, winning[2]), self.pick(johnson, winning[3])]

        self.assertTrue(all(r['is_winner'] for r in results))
        self.assertEqual((self.wallet(gbenga), self.wallet(johnson)), (Decimal('20.00'), Decimal('20.00')))
        self.assertIn('have been won', self.play(bloggs, MONTHLY).json()['error'])

    def test_unused_attempts_expire_and_november_surveys_count_for_december(self):
        gbenga = self.surveyed('O Gbenga', 200, 15)
        self.freeze(datetime.datetime(2026, 11, 15, 15, 0, tzinfo=datetime.timezone.utc))
        self.assertEqual(self.status(gbenga)['monthly_plays_available'], 0)      # October attempts are gone

        SurveyResponse.objects.bulk_create([SurveyResponse(user=gbenga, survey=self.survey, completed_at=timezone.now())
                                            for _ in range(100)])
        self.set_surveys(gbenga, 300)
        status = self.status(gbenga)
        self.assertEqual(status['monthly_plays_available'], 1)                   # November's 100 -> 1 Dec draw
        self.assertEqual(status['monthly_draw_day'], datetime.date(2026, 12, 1))


class TestDateMovesOnTests(DrawTestCase):
    """Moving MONTHLY_DRAW_TEST_DATE on must not skip settling the earlier test day."""

    def test_earlier_test_day_is_still_paid_after_the_setting_moves_on(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        utc = lambda *a: datetime.datetime(*a, tzinfo=datetime.timezone.utc)
        base = {**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5, 'MONTHLY_SURVEYS_REQUIRED': 100}
        self.freeze(utc(2030, 6, 8, 12))
        holders = []
        for _ in range(3):
            user = self.make_user(self.us, 100)
            SurveyResponse.objects.bulk_create([SurveyResponse(user=user, survey=self.survey, completed_at=timezone.now())
                                                for _ in range(100)])
            holders.append(user)

        with override_settings(LUCKY_DRAW_CONFIG={**base, 'MONTHLY_DRAW_TEST_DATE': '2030-06-08'}):
            self.client.force_login(holders[0])
            self.client.get(reverse('surveys:lucky_draw'))                      # draw opens on the 8th: recorded

        self.freeze(utc(2030, 6, 9, 12)); cache.clear()                       # 8th over in New York
        with override_settings(LUCKY_DRAW_CONFIG={**base, 'MONTHLY_DRAW_TEST_DATE': '2030-06-09'}):
            self.client.get(reverse('surveys:home'))                            # any visit settles

        for user in holders:
            self.assertEqual(user.profile.__class__.objects.get(user=user).wallet_balance, Decimal('10.00'))
        self.assertTrue(MonthlyDrawSettlement.objects.filter(country=self.us, draw_date=datetime.date(2030, 6, 8)).exists())

    def test_settle_command_with_date_and_dry_run(self):
        utc = lambda *a: datetime.datetime(*a, tzinfo=datetime.timezone.utc)
        self.freeze(utc(2030, 6, 8, 12))
        user = self.make_user(self.us, 100)
        SurveyResponse.objects.bulk_create([SurveyResponse(user=user, survey=self.survey, completed_at=timezone.now())
                                            for _ in range(100)])
        self.freeze(utc(2030, 6, 10, 12))
        with override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'MONTHLY_MIN_QUALIFIERS': 5,
                                                  'MONTHLY_DRAW_TEST_DATE': None}):
            out = StringIO()
            call_command('settle_monthly_draws', date=['2030-06-08'], dry_run=True, stdout=out)
            self.assertIn(f'would pay {user.email}: 1 x $10 USD = $10', out.getvalue())
            self.assertEqual(user.profile.__class__.objects.get(user=user).wallet_balance, Decimal('0.00'))

            call_command('settle_monthly_draws', date=['2030-06-08'], stdout=StringIO())
            self.assertEqual(user.profile.__class__.objects.get(user=user).wallet_balance, Decimal('10.00'))


@override_settings(LUCKY_DRAW_CONFIG={**DRAW_CONFIG, 'SHOW_NUMBERS_FOR_TESTING': False, 'MONTHLY_MIN_QUALIFIERS': 5,
                                      'MONTHLY_DRAW_TEST_DATE': None}, ADMIN_EMAIL='admin@example.com')
class DrawClosedAdminEmailTests(DrawTestCase):
    """The admin gets one email per country when its Monthly draw day closes."""

    def qualifier(self, country, surveys=100):
        user = self.make_user(country, surveys)
        SurveyResponse.objects.bulk_create([SurveyResponse(user=user, survey=self.survey, completed_at=self.NOW)
                                            for _ in range(surveys)])
        return user

    def settle(self, country):
        mail.outbox.clear()
        LuckyDrawView().settle_due_monthly_draws(CountryLuckyDrawConfig.objects.get(country=country))
        return [m for m in mail.outbox if m.subject.startswith('Monthly draw closed') and '01 June 2030' in m.subject]

    def test_no_draw_email_lists_the_automatic_payouts(self):
        users = [self.qualifier(self.us, 200), self.qualifier(self.us, 100)]                    # 3 attempts
        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))

        sent = self.settle(self.us)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].to, ['admin@example.com'])
        self.assertIn('Monthly draw closed: United States, 01 June 2030 (no draw - automatic payouts)', sent[0].subject)
        self.assertIn('Qualified attempts: 3 of 5 needed', sent[0].body)
        self.assertIn(f'{users[0].email}> - 2 x $10 USD = $20', sent[0].body)
        self.assertIn('Paid automatically: $30.', sent[0].body)

    def test_draw_ran_email_lists_the_winners_and_is_sent_once(self):
        players = [self.qualifier(self.uk) for _ in range(6)]
        self.assertTrue(self.play(players[0], MONTHLY, win=True).json()['is_winner'])
        self.play(players[1], MONTHLY, win=False)
        self.freeze(self.NOW + datetime.timedelta(days=1))

        sent = self.settle(self.uk)
        again = self.settle(self.uk)

        self.assertEqual(len(sent), 1)
        self.assertEqual(again, [])
        self.assertIn('(draw ran)', sent[0].subject)
        self.assertIn('Plays: 2. Winners: 1.', sent[0].body)
        self.assertIn(players[0].email, sent[0].body)
        self.assertIn('Winning numbers', sent[0].alternatives[0][0])

    def test_a_failing_email_does_not_stop_the_payout(self):
        user = self.qualifier(self.us)
        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))
        with mock.patch('surveys.lucky_draw.send_monthly_draw_closed_admin_notification', side_effect=RuntimeError('smtp down')):
            LuckyDrawView().settle_due_monthly_draws(CountryLuckyDrawConfig.objects.get(country=self.us))

        self.assertEqual(user.profile.__class__.objects.get(user=user).wallet_balance, Decimal('10.00'))

    def test_no_email_for_a_day_where_nothing_happened(self):
        self.freeze(self.NOW + datetime.timedelta(days=1, hours=6))
        mail.outbox.clear()

        LuckyDrawView().settle_due_monthly_draws(CountryLuckyDrawConfig.objects.get(country=self.ng))

        self.assertFalse([m for m in mail.outbox if m.subject.startswith('Monthly draw closed')])
