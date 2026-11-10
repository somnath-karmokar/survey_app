"""The survey "Thank you" message, and the Quick draw nudge added to it.

The Quick draw gives one play for every QUESTIONS_REQUIRED survey questions
answered. When a user finishes a survey without a play waiting, the "Thank you"
message also says how many more questions unlock the next play.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from surveys.lucky_draw import LuckyDrawView, quick_draw_nudge_text
from surveys.models import (
    Country, LuckyDrawEntry, Poll, PollResponse, Question, Survey, SurveyCategory,
)
from surveys.views_surveys import thank_you_message

THANK_YOU = 'Thank you for completing the survey!'

LUCKY_DRAW = {**settings.LUCKY_DRAW_CONFIG, 'QUESTIONS_REQUIRED': 4, 'POLLS_REQUIRED': 5,
              'MONTHLY_DRAW_TEST_DATE': None}
SURVEY_CONFIG = {**settings.SURVEY_CONFIG, 'AD_FREQUENCY': 1000, 'MONTHLY_SURVEY_CAP': None}


@override_settings(LUCKY_DRAW_CONFIG=LUCKY_DRAW, SURVEY_CONFIG=SURVEY_CONFIG)
class SurveyCompletionMessageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='nudge@example.com', email='nudge@example.com', password='pw',
        )
        self.country = Country.objects.create(name='United States', code='US')
        self.user.profile.country = self.country
        self.user.profile.save(update_fields=['country'])
        self.client.force_login(self.user)

    def make_survey(self, name, question_count=3):
        category = SurveyCategory.objects.create(name=f'{name} category', country=self.country)
        survey = Survey.objects.create(name=name, category=category, is_active=True)
        for order in range(question_count):
            question = Question.objects.create(
                question_text=f'{name} question {order}', question_type='text', order=order,
            )
            question.surveys.add(survey)
        return survey

    def complete_paged(self, survey):
        """Answer every question of `survey` through the paged flow."""
        response = None
        for index, question in enumerate(survey.questions.order_by('order', 'id')):
            response = self.client.post(
                reverse('surveys:survey_question', args=[survey.id, index]),
                {f'question_{question.id}': 'an answer'},
                follow=True,
            )
        return response

    def test_nudge_text(self):
        self.assertEqual(quick_draw_nudge_text(1), 'Answer 1 more survey question to unlock your next Quick draw play.')
        self.assertEqual(quick_draw_nudge_text(7), 'Answer 7 more survey questions to unlock your next Quick draw play.')

    def test_finishing_short_of_a_play_adds_the_nudge_as_one_message(self):
        response = self.complete_paged(self.make_survey('First', question_count=3))

        texts = [str(message) for message in response.context['messages']]
        self.assertEqual(len(texts), 1)                                   # one combined alert
        self.assertTrue(texts[0].startswith(f'{THANK_YOU} {quick_draw_nudge_text(1)}'))
        self.assertIn('has been added to your wallet for completing the', texts[0])   # category reward

    def test_no_nudge_once_a_play_is_waiting(self):
        response = self.complete_paged(self.make_survey('First', question_count=4))

        self.assertEqual(response.redirect_chain[-1][0], reverse('surveys:lucky_draw'))
        self.assertContains(response, THANK_YOU)
        self.assertNotContains(response, 'to unlock your next Quick draw play')

    def test_nudge_counts_from_the_last_play(self):
        self.complete_paged(self.make_survey('First', question_count=4))
        LuckyDrawEntry.objects.create(
            user=self.user, draw_type=LuckyDrawEntry.DRAW_TYPE_SURVEY,
            guessed_number=3, winning_number=9, is_winner=False, surveys_at_play=4, polls_at_play=0,
        )

        self.assertEqual(thank_you_message(self.user), f'{THANK_YOU} {quick_draw_nudge_text(4)}')

    @override_settings(LUCKY_DRAW_CONFIG={**LUCKY_DRAW, 'POLLS_REQUIRED': 1})
    def test_a_waiting_poll_draw_play_does_not_hide_the_nudge(self):
        poll = Poll.objects.create(title='A poll', country=self.country)
        PollResponse.objects.create(user=self.user, poll=poll)
        self.assertTrue(LuckyDrawView().get_eligibility_context(self.user)['poll_eligible'])

        self.assertEqual(LuckyDrawView().quick_draw_nudge(self.user), quick_draw_nudge_text(4))
