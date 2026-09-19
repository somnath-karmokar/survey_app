"""The survey "Thank you" message, and the Quick draw nudge added to it.

Every 2 surveys qualify a user for a draw play. When a user has just completed
a survey and exactly one more would qualify them, the "Thank you" message also
says so.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from surveys.lucky_draw import QUICK_DRAW_NUDGE, LuckyDrawView
from surveys.models import (
    Country, LuckyDrawEntry, Question, Survey, SurveyCategory, SurveyResponse,
    UserSurveyProgress,
)
from surveys.views_surveys import thank_you_message

THANK_YOU = 'Thank you for completing the survey!'
COMBINED = f'{THANK_YOU} {QUICK_DRAW_NUDGE}'

LUCKY_DRAW = {**settings.LUCKY_DRAW_CONFIG, 'SURVEYS_REQUIRED': 2, 'POLLS_REQUIRED': 5}


@override_settings(LUCKY_DRAW_CONFIG=LUCKY_DRAW)
class SurveyCompletionMessageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='nudge@example.com', email='nudge@example.com', password='pw',
        )
        self.country = Country.objects.create(name='United States', code='US')
        self.user.profile.country = self.country
        self.user.profile.save(update_fields=['country'])
        self.client.force_login(self.user)

    def make_survey(self, name, category=None, question_count=1):
        category = category or SurveyCategory.objects.create(name=f'{name} category', country=self.country)
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

    # -- the message itself ---------------------------------------------------

    def test_first_survey_adds_the_quick_draw_nudge_to_the_thank_you(self):
        response = self.complete_paged(self.make_survey('First'))

        self.assertContains(response, COMBINED)

    def test_message_is_a_single_combined_alert(self):
        response = self.complete_paged(self.make_survey('First'))

        texts = [str(message) for message in response.context['messages']]
        self.assertEqual(texts, [COMBINED])

    def test_no_nudge_once_the_user_qualifies(self):
        self.complete_paged(self.make_survey('First'))
        response = self.complete_paged(self.make_survey('Second'))

        # Two surveys qualify the user, so they are sent to the draw...
        self.assertEqual(response.redirect_chain[-1][0], reverse('surveys:lucky_draw'))
        self.assertContains(response, THANK_YOU)
        # ...and are not told to do one more.
        self.assertNotContains(response, QUICK_DRAW_NUDGE)

    def test_nudge_returns_after_the_draw_has_been_played(self):
        self.complete_paged(self.make_survey('First'))
        self.complete_paged(self.make_survey('Second'))
        # The user plays the draw, using up the two qualifying surveys.
        LuckyDrawEntry.objects.create(
            user=self.user, draw_type=LuckyDrawEntry.DRAW_TYPE_SURVEY,
            guessed_number=3, winning_number=9, is_winner=False,
            surveys_at_play=2, polls_at_play=0,
        )

        response = self.complete_paged(self.make_survey('Third'))

        self.assertContains(response, COMBINED)

    # -- the rule behind it ---------------------------------------------------

    def set_completed(self, count):
        UserSurveyProgress.objects.update_or_create(
            user=self.user, category=SurveyCategory.objects.get_or_create(
                name='Counting', country=self.country)[0],
            level=1, defaults={'completed_count': count},
        )

    def test_nudge_only_when_exactly_one_more_survey_is_needed(self):
        cases = [(0, ''), (1, QUICK_DRAW_NUDGE), (2, ''), (3, '')]
        for completed, expected in cases:
            with self.subTest(completed=completed):
                self.set_completed(completed)
                self.assertEqual(LuckyDrawView().quick_draw_nudge(self.user), expected)

    def test_thank_you_message_helper(self):
        self.set_completed(1)
        self.assertEqual(thank_you_message(self.user), COMBINED)
        self.set_completed(0)
        self.assertEqual(thank_you_message(self.user), THANK_YOU)

    @override_settings(LUCKY_DRAW_CONFIG={**LUCKY_DRAW, 'SURVEYS_REQUIRED': 100})
    def test_follows_the_configured_requirement_not_a_hardcoded_two(self):
        # With 100 required, being 1 survey in is nowhere near "one more".
        self.set_completed(1)
        self.assertEqual(LuckyDrawView().quick_draw_nudge(self.user), '')
        self.set_completed(99)
        self.assertEqual(LuckyDrawView().quick_draw_nudge(self.user), QUICK_DRAW_NUDGE)
