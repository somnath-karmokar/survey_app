"""The Quick draw and the Monthly draw are two separate draws on /lucky-draw/.

Quick draw : every 2 surveys = 1 attempt, small prize, no winner cap.
Monthly    : 100 surveys = 1 attempt (200 = 2, ...), its own prize per country
             (10 / 10 GBP / 5 for Nigeria) and 4 winners a month per country.
"""
import json
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.lucky_draw import QUICK_DRAW_NUDGE, LuckyDrawView
from surveys.models import (
    Country, CountryLuckyDrawConfig, LuckyDrawEntry, SurveyCategory,
    UserSurveyProgress, WalletTransaction,
)

MONTHLY = LuckyDrawEntry.DRAW_TYPE_MONTHLY
QUICK = LuckyDrawEntry.DRAW_TYPE_SURVEY

DRAW_CONFIG = {
    **settings.LUCKY_DRAW_CONFIG,
    'SURVEYS_REQUIRED': 2,
    'POLLS_REQUIRED': 5,
    'MONTHLY_SURVEYS_REQUIRED': 100,
    'NUMBER_RANGE_START': 1,
    'NUMBER_RANGE_END': 21,
}


@override_settings(LUCKY_DRAW_CONFIG=DRAW_CONFIG)
class DrawTestCase(TestCase):
    """Countries + per-country config shared by the tests below."""

    @classmethod
    def setUpTestData(cls):
        def country(name, code, symbol, currency, quick, monthly):
            c = Country.objects.create(name=name, code=code)
            CountryLuckyDrawConfig.objects.create(
                country=c, prize_amount=quick, currency_symbol=symbol, currency_code=currency,
                monthly_prize_amount=monthly, monthly_winner_cap=4 if monthly is not None else None,
            )
            return c

        cls.uk = country('United Kingdom', 'GB', '£', 'GBP', Decimal('1.00'), Decimal('10.00'))
        cls.us = country('United States', 'US', '$', 'USD', Decimal('1.00'), Decimal('10.00'))
        cls.ng = country('Nigeria', 'NG', '$', 'USD', Decimal('0.50'), Decimal('5.00'))
        # Australia has a Quick draw config but takes no part in the Monthly draw.
        cls.au = country('Australia', 'AU', '$', 'USD', Decimal('1.00'), None)
        cls.category = SurveyCategory.objects.create(name='General', country=cls.us)

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
        client.get(reverse('surveys:lucky_draw'))           # seeds the board in the session
        grid = client.session['lucky_draw_grid']
        lucky = client.session['lucky_draw_number']
        index = grid.index(lucky) if win else grid.index(lucky) - 1   # -1 wraps to the last box
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


class MonthlyAttemptsTests(DrawTestCase):
    def test_100_surveys_is_one_attempt_and_200_is_two(self):
        cases = [(0, 0), (99, 0), (100, 1), (150, 1), (199, 1), (200, 2), (300, 3)]
        for surveys, attempts in cases:
            with self.subTest(surveys=surveys):
                user = self.make_user(self.uk, surveys)
                self.assertEqual(self.status(user)['monthly_plays_available'], attempts)

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

        self.assertNotContains(page, 'monthly-draw-panel')
