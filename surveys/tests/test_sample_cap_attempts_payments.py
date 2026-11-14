"""Category sample cap (10 per country, Nigeria unlimited), attempt timing
(Appendix 3) and the payment rules ($10 minimum, first withdrawal to a bank)."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.models import (
    Answer, Charity, Choice, Country, CountryLuckyDrawConfig, Question, Survey, SurveyCategory, SurveyResponse,
    UserProfile, WalletWithdrawalRequest,
)
from surveys.survey_progress import category_sample_status, full_survey_ids, response_attempts

SURVEY_CONFIG = {**settings.SURVEY_CONFIG, 'MONTHLY_SURVEY_CAP': None, 'AD_FREQUENCY': 1000}


def make_user(email, country):
    user = get_user_model().objects.create_user(username=email, email=email, password='pw')
    UserProfile.objects.filter(user=user).update(country=country)
    return get_user_model().objects.get(pk=user.pk)


def make_survey(country, name='Fast Food Chains', questions=6):
    category = SurveyCategory.objects.create(name=name, country=country)
    survey = Survey.objects.create(name=name, category=category)
    for n in range(questions):
        q = Question.objects.create(question_text=f'{name} question {n}', question_type='single_choice', order=n)
        q.surveys.add(survey)
        Choice.objects.create(question=q, choice_text='Yes')
    return survey


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG)
class SampleCapTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.ng = Country.objects.create(name='Nigeria', code='NG')
        CountryLuckyDrawConfig.objects.create(country=self.uk, category_sample_cap=2)
        CountryLuckyDrawConfig.objects.create(country=self.ng, category_sample_cap=None)
        self.survey = make_survey(self.uk)
        self.other = make_survey(self.uk, 'Cinema')
        for i in range(2):
            SurveyResponse.objects.create(user=make_user(f'done{i}@example.com', self.uk), survey=self.survey,
                                          completed_at=timezone.now())
        self.late = make_user('late@example.com', self.uk)
        self.client.force_login(self.late)

    def test_full_category_cannot_be_started(self):
        page = self.client.get(reverse('surveys:survey_detail', args=[self.survey.id]), follow=True)

        self.assertContains(page, 'has already collected all 2 responses needed in United Kingdom this month')
        self.assertContains(page, 'It opens again on 1 ')
        self.assertFalse(SurveyResponse.objects.filter(user=self.late).exists())
        self.assertEqual(self.client.get(reverse('surveys:survey_detail', args=[self.other.id])).status_code, 200)

    def test_lists_show_the_survey_as_full(self):
        self.assertContains(self.client.get(reverse('surveys:survey_list')), 'Survey full')
        page = self.client.get(reverse('surveys:category_detail', args=[self.survey.category.slug]))
        self.assertContains(page, 'Survey full')
        self.assertEqual(full_survey_ids(self.late, [self.survey, self.other]), {self.survey.id})

    def test_only_completed_surveys_count(self):
        survey = make_survey(self.uk, 'Airlines')
        SurveyResponse.objects.create(user=make_user('d@example.com', self.uk), survey=survey, completed_at=timezone.now())
        SurveyResponse.objects.create(user=make_user('s@example.com', self.uk), survey=survey)   # still answering

        status = category_sample_status(survey, self.late)
        self.assertEqual((status['completed'], status['in_progress'], status['full']), (1, 1, False))

    def test_someone_already_answering_can_finish_when_it_fills_up(self):
        starter = make_user('starter@example.com', self.uk)
        SurveyResponse.objects.create(user=starter, survey=self.survey)        # started; 2 of 2 completed already

        self.assertFalse(category_sample_status(self.survey, starter)['full'])   # can finish
        self.assertTrue(category_sample_status(self.survey, self.late)['full'])  # newcomer is locked out
        self.assertEqual(full_survey_ids(starter, [self.survey]), set())

    @override_settings(SURVEY_CONFIG=settings.SURVEY_CONFIG)
    def test_no_per_user_monthly_limit(self):
        self.assertIsNone(settings.SURVEY_CONFIG['MONTHLY_SURVEY_CAP'])
        self.assertIsNone(SurveyResponse.monthly_limit_status(self.late))

    def test_nigeria_is_unlimited(self):
        survey = make_survey(self.ng)
        for i in range(15):
            SurveyResponse.objects.create(user=make_user(f'ng{i}@example.com', self.ng), survey=survey,
                                          completed_at=timezone.now())

        status = category_sample_status(survey, make_user('ngnew@example.com', self.ng))
        self.assertEqual((status['cap'], status['full']), (None, False))

    def test_cap_defaults_to_10_without_a_country_config(self):
        ca = Country.objects.create(name='Canada', code='CA')
        survey = make_survey(ca)
        self.assertEqual(category_sample_status(survey)['cap'], 10)


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG)
class MonthlySampleCapTests(TestCase):
    """The cap counts one calendar month (country's time zone); a full category opens again on the 1st."""

    def setUp(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.london = ZoneInfo('Europe/London')
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        CountryLuckyDrawConfig.objects.create(country=self.uk, category_sample_cap=2, time_zone='Europe/London')
        self.survey = make_survey(self.uk)
        self.mid_nov = datetime(2026, 11, 15, 12, tzinfo=self.london)
        self.late = make_user('late@example.com', self.uk)

    def complete(self, n, when, prefix='u'):
        for i in range(n):
            r = SurveyResponse.objects.create(user=make_user(f'{prefix}{i}@example.com', self.uk), survey=self.survey)
            SurveyResponse.objects.filter(pk=r.pk).update(started_at=when, completed_at=when)

    def test_full_this_month(self):
        self.complete(2, self.mid_nov)
        status = category_sample_status(self.survey, self.late, at=self.mid_nov)
        self.assertTrue(status['full'])
        self.assertEqual(status['reopens_on'].date().isoformat(), '2026-12-01')
        self.assertEqual(full_survey_ids(self.late, [self.survey], at=self.mid_nov), {self.survey.id})

    def test_opens_again_next_month(self):
        self.complete(2, self.mid_nov)
        from datetime import datetime
        december = datetime(2026, 12, 1, 0, 5, tzinfo=self.london)
        status = category_sample_status(self.survey, self.late, at=december)
        self.assertEqual((status['completed'], status['full']), (0, False))
        self.assertEqual(full_survey_ids(self.late, [self.survey], at=december), set())

    def test_last_months_responses_do_not_count(self):
        from datetime import datetime
        self.complete(2, datetime(2026, 10, 31, 23, 30, tzinfo=self.london), prefix='oct')
        self.complete(1, self.mid_nov, prefix='nov')
        status = category_sample_status(self.survey, self.late, at=self.mid_nov)
        self.assertEqual((status['completed'], status['full']), (1, False))

    def test_month_follows_the_countrys_time_zone(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        CountryLuckyDrawConfig.objects.filter(country=self.uk).update(time_zone='America/New_York')
        # 20:00 New York on 30 November is already 1 December in UTC - still November there.
        evening = datetime(2026, 11, 30, 20, tzinfo=ZoneInfo('America/New_York'))
        self.complete(2, datetime(2026, 11, 10, 12, tzinfo=ZoneInfo('America/New_York')))
        self.assertTrue(category_sample_status(self.survey, self.late, at=evening)['full'])

    def test_unfinished_from_last_month_can_still_finish(self):
        from datetime import datetime
        starter = make_user('starter@example.com', self.uk)
        r = SurveyResponse.objects.create(user=starter, survey=self.survey)
        SurveyResponse.objects.filter(pk=r.pk).update(started_at=datetime(2026, 10, 20, tzinfo=self.london))
        self.complete(2, self.mid_nov)
        self.assertFalse(category_sample_status(self.survey, starter, at=self.mid_nov)['full'])   # can finish
        self.assertTrue(category_sample_status(self.survey, self.late, at=self.mid_nov)['full'])

    def test_people_still_answering_do_not_lock_it(self):
        self.complete(1, self.mid_nov)
        for i in range(3):
            r = SurveyResponse.objects.create(user=make_user(f's{i}@example.com', self.uk), survey=self.survey)
            SurveyResponse.objects.filter(pk=r.pk).update(started_at=self.mid_nov)
        self.assertFalse(category_sample_status(self.survey, self.late, at=self.mid_nov)['full'])

    def test_cap_change_in_admin_applies_immediately(self):
        self.complete(2, self.mid_nov)
        CountryLuckyDrawConfig.objects.filter(country=self.uk).update(category_sample_cap=3)
        self.assertFalse(category_sample_status(self.survey, self.late, at=self.mid_nov)['full'])
        CountryLuckyDrawConfig.objects.filter(country=self.uk).update(category_sample_cap=None)
        self.assertIsNone(category_sample_status(self.survey, self.late, at=self.mid_nov)['cap'])


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG)
class AttemptTimingTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.survey = make_survey(self.uk, questions=6)
        self.user = make_user('t@example.com', self.uk)
        self.client.force_login(self.user)
        self.questions = list(self.survey.questions.order_by('order', 'id'))

    def answer(self, index, seconds):
        q = self.questions[index]
        self.client.post(reverse('surveys:survey_question', args=[self.survey.id, index]),
                         {f'question_{q.id}': str(q.choices.first().id), 'elapsed_seconds': str(seconds)})

    def test_each_answer_records_when_and_how_long(self):
        self.answer(0, 40)

        answer = Answer.objects.get(question=self.questions[0])
        self.assertIsNotNone(answer.answered_at)
        self.assertEqual(answer.time_spent_seconds, 40)

    def test_answers_are_grouped_into_attempts_like_appendix_3(self):
        for i in range(3):
            self.answer(i, 60)                                   # attempt 1: Q1-Q3, 3 minutes
        response = SurveyResponse.objects.get(user=self.user)
        Answer.objects.filter(response=response).update(answered_at=timezone.now() - timedelta(hours=5))
        for i in range(3, 6):
            self.answer(i, 120)                                  # attempt 2 (5 hours later): Q4-Q6, 6 minutes

        attempts = response_attempts(response)
        self.assertEqual([(a['first'], a['last'], a['count'], a['seconds']) for a in attempts],
                         [('Q1', 'Q3', 3, 180), ('Q4', 'Q6', 3, 360)])

        admin = get_user_model().objects.create_superuser('admin@x.com', 'admin@x.com', 'pw')
        self.client.force_login(admin)
        report = self.client.get(reverse('admin:surveys_surveyresponse_change', args=[response.pk]))
        self.assertContains(report, 'id="attempts"')
        self.assertContains(report, '2 attempts')
        self.assertContains(report, 'Total time spent')
        self.assertContains(report, '9m 00s')


class PaymentRuleTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.user = make_user('pay@example.com', self.uk)
        self.client.force_login(self.user)
        Charity.objects.create(name='Children First')

    def set_balance(self, amount):
        UserProfile.objects.filter(user=self.user).update(wallet_balance=Decimal(amount))

    def test_withdrawal_needs_10_in_the_wallet(self):
        self.set_balance('9.99')
        page = self.client.get(reverse('surveys:wallet_withdrawal_request'), follow=True)
        self.assertContains(page, 'You need at least')
        self.assertContains(page, '10.00 in your wallet')

        self.set_balance('10.00')
        self.assertEqual(self.client.get(reverse('surveys:wallet_withdrawal_request')).status_code, 200)

    def test_first_withdrawal_only_into_a_bank_account(self):
        self.set_balance('20.00')
        form = self.client.get(reverse('surveys:wallet_withdrawal_request')).content.decode()
        self.assertIn('value="bank_transfer"', form)
        self.assertNotIn('value="charity"', form)
        self.assertNotIn('value="paypal"', form)
        self.assertIn('20% additional for users donating their withdrawals/winnings to charity', form)
        self.assertIn('From your next withdrawal you can choose', form)

        self.client.post(reverse('surveys:wallet_withdrawal_request'), {
            'full_name': 'Pay User', 'email': 'pay@example.com', 'amount': '10.00', 'country': self.uk.id,
            'payment_method': 'charity', 'charity': Charity.objects.get().id})
        self.assertFalse(WalletWithdrawalRequest.objects.exists())

    def test_donation_offered_from_the_second_withdrawal(self):
        self.set_balance('30.00')
        WalletWithdrawalRequest.objects.create(
            profile=UserProfile.objects.get(user=self.user), full_name='Pay User', email='pay@example.com',
            amount=Decimal('10.00'), payment_method='bank_transfer', status='approved')

        form = self.client.get(reverse('surveys:wallet_withdrawal_request')).content.decode()
        self.assertIn('value="charity"', form)
        self.assertIn('id="charity-promo"', form)
