"""Admin: dashboard, survey responses (who, what, how long), response report, user list."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from surveys.admin import format_duration
from surveys.models import (
    Answer, Choice, Country, Question, Survey, SurveyCategory, SurveyResponse, UserProfile, WalletTransaction,
)


class AdminPagesTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('admin@sudraw.com', 'admin@sudraw.com', 'pw')
        self.client.force_login(self.admin)
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        category = SurveyCategory.objects.create(name='Fast Food Chains', country=self.uk)
        self.survey = Survey.objects.create(name='Fast Food Chains', category=category)
        screening = Question.objects.create(question_text='Which have you visited?', question_type='multiple_choice', order=0)
        screening.surveys.add(self.survey)
        Choice.objects.create(question=screening, choice_text='KFC')
        Choice.objects.create(question=screening, choice_text='Foodie', is_disqualifying=True)
        self.q1 = Question.objects.create(question_text='Order speed\nHow fast was your order?', question_type='single_choice', order=1)
        self.q1.surveys.add(self.survey)
        self.fast = Choice.objects.create(question=self.q1, choice_text='Under 3 minutes')
        q2 = Question.objects.create(question_text='Anything else?', question_type='text', order=2)
        q2.surveys.add(self.survey)

        self.user = get_user_model().objects.create_user('jane@example.com', 'jane@example.com', 'pw',
                                                          first_name='Jane', last_name='Doe')
        UserProfile.objects.filter(user=self.user).update(country=self.uk)
        self.done = SurveyResponse.objects.create(user=self.user, survey=self.survey, time_spent_seconds=1930)
        SurveyResponse.objects.filter(pk=self.done.pk).update(completed_at=timezone.now())
        for q in (screening, self.q1, q2):
            a = Answer.objects.create(response=self.done, question=q)
            if q is self.q1:
                a.selected_choices.set([self.fast])
                a.text_answer = 'Drive-through only'
                a.save()
        profile = UserProfile.objects.get(user=self.user)
        WalletTransaction.objects.create(profile=profile, transaction_type='credit', amount=Decimal('2.00'),
                                         currency_code='GBP', currency_symbol='£', description='Survey category completed',
                                         survey_response=self.done, balance_after=Decimal('2.00'))
        other = get_user_model().objects.create_user('sam@example.com', 'sam@example.com', 'pw')
        self.open = SurveyResponse.objects.create(user=other, survey=self.survey, time_spent_seconds=95)
        Answer.objects.create(response=self.open, question=screening)

    def test_format_duration(self):
        self.assertEqual([format_duration(s) for s in (45, 1930, 3725)], ['45s', '32m 10s', '1h 02m'])

    def test_dashboard_shows_key_figures_recent_completions_and_sections(self):
        page = self.client.get(reverse('admin:index'))

        self.assertContains(page, 'Surveys completed today')
        self.assertContains(page, 'Surveys in progress')
        self.assertContains(page, 'Latest completed surveys')
        self.assertContains(page, 'jane@example.com')
        self.assertContains(page, '32m 10s')
        for section in ('Surveys', 'Users &amp; safety', 'Wallet &amp; payouts', 'Draws &amp; rewards'):
            self.assertContains(page, section)

    def test_responses_list_shows_who_what_how_long(self):
        page = self.client.get(reverse('admin:surveys_surveyresponse_changelist'))

        for text in ('Jane Doe', 'jane@example.com', 'United Kingdom', 'Fast Food Chains', 'Completed', 'In progress',
                     '3 / 3 questions', '1 / 3 questions', '32m 10s', '1m 35s', '£2.00 GBP'):
            self.assertContains(page, text)

    def test_status_filter_and_user_link(self):
        completed = self.client.get(reverse('admin:surveys_surveyresponse_changelist') + '?status=completed')
        self.assertContains(completed, 'jane@example.com')
        self.assertNotContains(completed, 'sam@example.com')

        by_user = self.client.get(reverse('admin:surveys_surveyresponse_changelist') + f'?user__id__exact={self.user.pk}')
        self.assertEqual(by_user.status_code, 200)
        self.assertNotContains(by_user, 'sam@example.com')

    def test_response_report_lists_every_question_and_answer(self):
        page = self.client.get(reverse('admin:surveys_surveyresponse_change', args=[self.done.pk]))

        for text in ('Jane Doe · Fast Food Chains', 'Completed', '32m 10s', 'Order speed', 'How fast was your order?',
                     'Under 3 minutes, Other: Drive-through only', 'Screening', '£2.00 GBP'):
            self.assertContains(page, text)
        in_progress = self.client.get(reverse('admin:surveys_surveyresponse_change', args=[self.open.pk]))
        self.assertContains(in_progress, 'Not answered yet')

    def test_csv_export(self):
        response = self.client.post(reverse('admin:surveys_surveyresponse_changelist'), {
            'action': 'export_csv', '_selected_action': [self.done.pk, self.open.pk]})

        body = response.content.decode()
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('Time taken (seconds)', body)
        self.assertIn('jane@example.com,United Kingdom,Fast Food Chains,Completed,3,3,32m 10s,1930', body)

    def test_user_list_shows_survey_counts_and_status(self):
        page = self.client.get(reverse('admin:auth_user_changelist'))

        self.assertContains(page, 'Jane Doe')
        self.assertContains(page, '<strong>1</strong> completed', html=False)
        self.assertContains(page, f'?user__id__exact={self.user.pk}')
        self.assertContains(page, 'Active')

    def test_other_admin_pages_still_render(self):
        for name in ('surveys_surveycategory_changelist', 'surveys_survey_changelist', 'surveys_question_changelist',
                     'surveys_walletwithdrawalrequest_changelist', 'surveys_wallettransaction_changelist',
                     'surveys_luckydrawentry_changelist', 'surveys_surveysuspension_changelist', 'surveys_charity_changelist',
                     'surveys_countryluckydrawconfig_changelist', 'auth_group_changelist'):
            self.assertEqual(self.client.get(reverse(f'admin:{name}')).status_code, 200, name)
        self.assertEqual(self.client.get(reverse('admin:surveys_survey_change', args=[self.survey.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin:auth_user_change', args=[self.user.pk])).status_code, 200)
