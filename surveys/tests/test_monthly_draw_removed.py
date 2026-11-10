"""The Monthly draw is switched off (LUCKY_DRAW_CONFIG['MONTHLY_DRAW_ENABLED'] = False).

Runs with the real settings: even a country with a Monthly prize and a user with
plenty of surveys gets no Monthly tab, card, attempt or payout. The Quick draw
(one play per 30 questions) is unaffected.
"""
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from surveys.lucky_draw import LuckyDrawView, monthly_draw_enabled
from surveys.models import (
    Country, CountryLuckyDrawConfig, LuckyDrawEntry, MonthlyDrawSettlement, SurveyCategory, UserSurveyProgress,
)

FIRST_OF_MONTH = datetime.datetime(2030, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)


@override_settings(LUCKY_DRAW_CONFIG={**settings.LUCKY_DRAW_CONFIG, 'MONTHLY_DRAW_TEST_DATE': None})
class MonthlyDrawRemovedTests(TestCase):
    def setUp(self):
        mock.patch('django.utils.timezone.now', return_value=FIRST_OF_MONTH).start()
        self.addCleanup(mock.patch.stopall)
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        CountryLuckyDrawConfig.objects.create(
            country=self.uk, prize_amount=Decimal('1.00'), currency_symbol='£', currency_code='GBP',
            monthly_prize_amount=Decimal('10.00'), monthly_winner_cap=4, time_zone='Europe/London',
        )
        self.user = get_user_model().objects.create_user(username='m@example.com', email='m@example.com', password='pw')
        self.user.profile.country = self.uk
        self.user.profile.save()
        category = SurveyCategory.objects.create(name='Fast Food', country=self.uk)
        UserSurveyProgress.objects.create(user=self.user, category=category, level=1, completed_count=500)
        self.client.force_login(self.user)

    def test_switched_off_in_settings(self):
        self.assertFalse(settings.LUCKY_DRAW_CONFIG['MONTHLY_DRAW_ENABLED'])
        self.assertFalse(monthly_draw_enabled())

    def test_no_monthly_attempts_even_with_500_surveys_on_the_1st(self):
        eligibility = LuckyDrawView().get_eligibility_context(self.user)

        self.assertFalse(eligibility['monthly_available'])
        self.assertFalse(eligibility['monthly_eligible'])
        self.assertNotIn(LuckyDrawEntry.DRAW_TYPE_MONTHLY, eligibility['eligible_draw_types'])

    def test_draw_page_has_no_monthly_tab_or_panel(self):
        page = self.client.get(reverse('surveys:lucky_draw'))

        self.assertNotContains(page, 'data-draw-type="monthly"')
        self.assertNotContains(page, 'id="monthly-draw-panel"')
        self.assertNotContains(page, 'Monthly Draw')

    def test_monthly_play_is_refused(self):
        response = self.client.post(reverse('surveys:lucky_draw'), data=json.dumps({'index': 0, 'draw_type': 'monthly'}),
                                    content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('no longer available', response.json()['error'])
        self.assertFalse(LuckyDrawEntry.objects.filter(draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY).exists())

    def test_profile_and_dashboard_have_no_monthly_card(self):
        for name in ('surveys:user_profile', 'surveys:dashboard'):
            self.assertNotContains(self.client.get(reverse(name)), 'Monthly Draw Milestone')

    def test_no_automatic_monthly_payouts(self):
        self.client.get(reverse('surveys:dashboard'))

        self.assertFalse(MonthlyDrawSettlement.objects.exists())
        self.assertFalse(LuckyDrawEntry.objects.filter(draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY).exists())

    def test_quick_draw_is_one_play_per_30_questions(self):
        self.assertEqual(LuckyDrawView().quick_draw_questions_required(), 30)
