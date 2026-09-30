"""The Quick draw and the Monthly draw are two separate draws on /lucky-draw/.

Quick draw : every 2 surveys = 1 attempt, small prize, no winner cap.
Monthly    : 100 surveys = 1 attempt (200 = 2, ...), its own prize per country
             (10 / 10 GBP / 5 for Nigeria) and 4 winners a month per country.
             Only playable on the 1st of the month (00:00-23:59 local time).
"""
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.lucky_draw import QUICK_DRAW_NUDGE, LuckyDrawView
from surveys.models import (
    Country, CountryLuckyDrawConfig, LuckyDrawEntry, Survey, SurveyCategory,
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
        suffix = '_monthly' if draw_type == MONTHLY and 'lucky_draw_grid_monthly' in client.session else ''
        grid = client.session['lucky_draw_grid' + suffix]
        lucky = client.session['lucky_draw_number' + suffix]
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
        """A user whose milestone(s) were reached with real completions dated
        before this (frozen) month, so they hold a banked Monthly attempt but
        don't count toward THIS month's newly-reached-milestone quorum.
        """
        user = self.make_user(country, total_surveys)
        before_this_month = self.NOW.replace(day=1) - datetime.timedelta(days=1)
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
        self.assertEqual(stats['qualified_users'], 2)

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
        self.assertIn('A: J. Okafor', error)
        self.assertIn('B: B. Ade', error)

        self.client.force_login(latecomer)
        page = self.client.get(reverse('surveys:lucky_draw'))
        self.assertContains(page, 'Winners:')
        self.assertContains(page, 'A: J. Okafor')

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
        self.assertContains(page, 'attempt will be waiting')

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

    def test_a_banked_attempt_from_before_this_month_does_not_count_toward_quorum(self):
        for _ in range(4):
            self.make_new_qualifier(self.us, 100)                      # only 4 new this month
        blocked_player = self.make_banked_qualifier(self.us, 100)      # personally eligible, but not a new crosser

        self.assertEqual(self.status(blocked_player)['monthly_plays_available'], 1)
        self.assertFalse(self.status(blocked_player)['monthly_quorum_met'])

        response = self.play(blocked_player, MONTHLY)

        self.assertEqual(response.status_code, 400)
        self.assertIn('Not enough people', response.json()['error'])
        self.assertIn('4 of 5 needed', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(user=blocked_player).exists())
        self.assertEqual(self.status(blocked_player)['monthly_plays_available'], 1)     # attempt kept

    def test_page_explains_the_quorum_is_not_met(self):
        for _ in range(4):
            self.make_new_qualifier(self.us, 100)
        user = self.make_banked_qualifier(self.us, 100)
        self.client.force_login(user)

        page = self.client.get(reverse('surveys:lucky_draw'))

        self.assertContains(page, 'Not enough people')
        self.assertContains(page, '4 of 5 needed')

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
        self.assertIn(self.client.session['lucky_draw_number_monthly'], range(1, 6))
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
