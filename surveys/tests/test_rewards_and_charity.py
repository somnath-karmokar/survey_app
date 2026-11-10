"""90-day lock on completed surveys, a commercial every 5 questions, the wallet
reward per completed category ($2, $1 in Nigeria), donating withdrawals to
charity (+20% from Sudraw) and the homepage charity strip."""
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from surveys.models import (
    Charity, Choice, Country, CountryLuckyDrawConfig, Question, Survey, SurveyCategory, SurveyResponse, UserProfile,
    WalletTransaction, WalletWithdrawalRequest,
)
from surveys.rewards import credit_category_completion

SURVEY_CONFIG = {**settings.SURVEY_CONFIG, 'MONTHLY_SURVEY_CAP': None}
MAIN_QUESTIONS = 12


def make_survey(country, name='Fast Food'):
    category = SurveyCategory.objects.create(name=name, country=country)
    survey = Survey.objects.create(name=name, category=category, level=1)
    screening = Question.objects.create(question_text='Which have you visited?', question_type='multiple_choice', order=0)
    screening.surveys.add(survey)
    Choice.objects.create(question=screening, choice_text='Real brand')
    Choice.objects.create(question=screening, choice_text='Made-up brand', is_disqualifying=True)
    for n in range(1, MAIN_QUESTIONS + 1):
        q = Question.objects.create(question_text=f'Question {n}', question_type='single_choice', order=n)
        q.surveys.add(survey)
        Choice.objects.create(question=q, choice_text='Yes')
    return survey


def make_user(country, email):
    user = get_user_model().objects.create_user(username=email, email=email, password='pw')
    user.profile.country = country
    user.profile.save()
    return user


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG)
class SurveyFlowTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        CountryLuckyDrawConfig.objects.create(country=self.uk, prize_amount=Decimal('1.00'), currency_symbol='£',
                                              currency_code='GBP', category_completion_reward=Decimal('2.00'))
        self.survey = make_survey(self.uk)
        self.questions = list(self.survey.questions.order_by('order', 'id'))
        self.user = make_user(self.uk, 'flow@example.com')
        self.client.force_login(self.user)

    def answer(self, index):
        question = self.questions[index]
        value = str(question.choices.order_by('id').first().id)
        data = {f'question_{question.id}': [value] if question.question_type == 'multiple_choice' else value}
        return self.client.post(reverse('surveys:survey_question', args=[self.survey.id, index]), data)

    def complete(self):
        response = None
        for index in range(len(self.questions)):
            response = self.answer(index)
            if response.status_code == 200:                 # commercial shown: submit again to move on
                response = self.answer(index)
        return response

    def test_settings(self):
        self.assertEqual(settings.SURVEY_CONFIG['DEFAULT_COOLDOWN_DAYS'], 90)
        self.assertEqual(settings.SURVEY_CONFIG['AD_FREQUENCY'], 5)

    def test_commercial_after_every_5_questions(self):
        shown_after = []
        for index in range(len(self.questions) - 1):
            response = self.answer(index)
            if response.status_code == 200 and 'advertisementModal' in response.content.decode() \
                    and "modal.show()" in response.content.decode():
                shown_after.append(index)                    # index = question number (screening is index 0)
                self.answer(index)
        self.assertEqual(shown_after, [5, 10])

    def test_completed_category_adds_2_to_the_wallet_once(self):
        self.complete()

        response = SurveyResponse.objects.get(user=self.user)
        self.assertIsNotNone(response.completed_at)
        self.assertEqual(UserProfile.objects.get(user=self.user).wallet_balance, Decimal('2.00'))
        reward = WalletTransaction.objects.get(survey_response=response)
        self.assertEqual((reward.amount, reward.transaction_type), (Decimal('2.00'), 'credit'))
        self.assertIsNone(credit_category_completion(response))               # never paid twice
        self.assertEqual(UserProfile.objects.get(user=self.user).wallet_balance, Decimal('2.00'))

    def test_completed_survey_is_closed_for_90_days(self):
        self.complete()

        page = self.client.get(reverse('surveys:survey_detail', args=[self.survey.id]), follow=True)
        self.assertContains(page, 'Please wait 90 more days')
        self.assertContains(self.client.get(reverse('surveys:survey_list')), 'Available in 90 days')


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG)
class NigeriaRewardTests(TestCase):
    def test_nigeria_gets_1(self):
        ng = Country.objects.create(name='Nigeria', code='NG')
        user = make_user(ng, 'ng@example.com')
        survey = make_survey(ng)
        response = SurveyResponse.objects.create(user=user, survey=survey)

        credit_category_completion(response)

        self.assertEqual(UserProfile.objects.get(user=user).wallet_balance, Decimal('1.00'))


class CharityDonationTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.charity = Charity.objects.create(name='Children First')
        self.user = make_user(self.uk, 'give@example.com')
        self.client.force_login(self.user)
        # After logging in: the login save re-saves the profile with its old balance.
        UserProfile.objects.filter(user=self.user).update(wallet_balance=Decimal('25.00'))
        # Donations are offered from the second withdrawal (the first must go to a bank).
        WalletWithdrawalRequest.objects.create(
            profile=UserProfile.objects.get(user=self.user), full_name='Earlier', email='give@example.com',
            amount=Decimal('10.00'), payment_method='bank_transfer', status='approved')

    def donate(self, amount='10.00', charity=True):
        data = {'full_name': 'Jane Giver', 'email': 'give@example.com', 'amount': amount,
                'country': self.uk.id, 'payment_method': 'charity'}
        if charity:
            data['charity'] = self.charity.id
        return self.client.post(reverse('surveys:wallet_withdrawal_request'), data, follow=True)

    def test_donating_10_sends_12_to_the_charity_and_takes_10_from_the_wallet(self):
        page = self.donate('10.00')

        self.assertContains(page, 'the charity will receive')
        request = WalletWithdrawalRequest.objects.get(payment_method='charity')
        self.assertEqual((request.charity, request.amount, request.charity_bonus_amount, request.charity_total_amount),
                         (self.charity, Decimal('10.00'), Decimal('2.00'), Decimal('12.00')))

        request.approve()

        self.assertEqual(UserProfile.objects.get(user=self.user).wallet_balance, Decimal('15.00'))
        self.assertIn('Children First', request.wallet_transaction.description)
        self.assertIn('12.00', request.wallet_transaction.description)

    def test_a_charity_must_be_chosen(self):
        page = self.donate(charity=False)

        self.assertContains(page, 'Please choose the charity to donate to.')
        self.assertFalse(WalletWithdrawalRequest.objects.filter(payment_method='charity').exists())

    def test_withdrawal_page_offers_the_charity_and_shows_the_bonus(self):
        page = self.client.get(reverse('surveys:wallet_withdrawal_request'))

        self.assertContains(page, 'Donate to charity (+20% from Sudraw)')
        self.assertContains(page, 'Children First')
        self.assertContains(page, 'id="charity-promo"')

    def test_no_charity_option_without_an_active_charity(self):
        Charity.objects.update(is_active=False)

        self.assertNotContains(self.client.get(reverse('surveys:wallet_withdrawal_request')), 'Donate to charity')

    def test_homepage_promotes_the_20_percent(self):
        page = self.client.get(reverse('surveys:home'))

        self.assertContains(page, 'id="charity-strip"')
        self.assertContains(page, '+20%')
        self.assertContains(page, 'the charity receives 12')
