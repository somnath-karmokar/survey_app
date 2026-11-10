"""Surveys in parts: saved answers and resume, one category at a time, the
"Other (please specify)" box, the survey timer and the Quick draw every 30 questions."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.conf import settings
from django.urls import reverse

from surveys.lucky_draw import LuckyDrawView
from surveys.models import (
    Answer, Choice, Country, LuckyDrawEntry, Question, Survey, SurveyCategory, SurveyResponse, UserSurveyProgress,
)

SURVEY_CONFIG = {**settings.SURVEY_CONFIG, 'SURVEY_PARTS': 8, 'AD_FREQUENCY': 1000, 'MONTHLY_SURVEY_CAP': None}
DRAW_CONFIG = {**settings.LUCKY_DRAW_CONFIG, 'QUESTIONS_REQUIRED': 30, 'MONTHLY_DRAW_TEST_DATE': None}
MAIN_QUESTIONS = 120


def make_survey(country, name):
    category = SurveyCategory.objects.create(name=name, country=country)
    survey = Survey.objects.create(name=name, category=category, level=1)
    screening = Question.objects.create(question_text='Which have you visited?', question_type='multiple_choice', order=0)
    screening.surveys.add(survey)
    Choice.objects.create(question=screening, choice_text='Real brand')
    Choice.objects.create(question=screening, choice_text='Made-up brand', is_disqualifying=True)
    questions = Question.objects.bulk_create([
        Question(question_text=f'{name} question {n}', question_type='single_choice', order=n)
        for n in range(1, MAIN_QUESTIONS + 1)
    ])
    Question.surveys.through.objects.bulk_create(
        [Question.surveys.through(question_id=q.id, survey_id=survey.id) for q in questions])
    Choice.objects.bulk_create([Choice(question=q, choice_text=t) for q in questions for t in ('Yes', 'No')])
    return survey


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG, LUCKY_DRAW_CONFIG=DRAW_CONFIG)
class SurveyPartsBase(TestCase):
    """Two 120-question categories and a logged-in user (shared setup)."""
    @classmethod
    def setUpTestData(cls):
        cls.uk = Country.objects.create(name='United Kingdom', code='GB')
        cls.survey = make_survey(cls.uk, 'Fast Food')
        cls.other_survey = make_survey(cls.uk, 'Airlines')
        cls.questions = list(cls.survey.questions.order_by('order', 'id'))

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='p@example.com', email='p@example.com', password='pw')
        self.user.profile.country = self.uk
        self.user.profile.save()
        self.client.force_login(self.user)

    def url(self, index, survey=None):
        return reverse('surveys:survey_question', args=[(survey or self.survey).id, index])

    def answer(self, index, extra=None, survey=None):
        question = (survey or self.survey).questions.order_by('order', 'id')[index]
        first = question.choices.order_by('id').first()
        data = {f'question_{question.id}': [str(first.id)] if question.question_type == 'multiple_choice' else str(first.id)}
        data.update(extra or {})
        return self.client.post(self.url(index, survey), data)

    def answer_up_to(self, last_index):
        for index in range(last_index + 1):
            self.answer(index)



class SurveyPartsTests(SurveyPartsBase):
    def test_answers_are_saved_as_you_go_and_the_survey_resumes(self):
        self.answer_up_to(3)

        response = SurveyResponse.objects.get(user=self.user, survey=self.survey)
        self.assertIsNone(response.completed_at)
        self.assertEqual(response.answers.count(), 4)
        resume = self.client.get(reverse('surveys:survey_detail', args=[self.survey.id]))
        self.assertRedirects(resume, self.url(4))

    def test_questions_cannot_be_skipped_but_earlier_ones_can_be_revisited(self):
        self.answer_up_to(3)

        self.assertRedirects(self.client.get(self.url(50)), self.url(4))
        back = self.client.get(self.url(2))
        self.assertEqual(back.status_code, 200)
        self.assertContains(back, 'checked')                                      # saved answer restored

    def test_another_category_is_blocked_until_the_survey_is_finished(self):
        self.answer_up_to(2)

        page = self.client.get(reverse('surveys:survey_detail', args=[self.other_survey.id]), follow=True)

        self.assertEqual(page.redirect_chain[-1][0], self.url(3))
        self.assertContains(page, 'before starting another category')
        self.assertFalse(SurveyResponse.objects.filter(survey=self.other_survey).exists())
        self.assertContains(self.client.get(reverse('surveys:survey_list')), 'id="continue-survey-banner"')

    def test_shown_as_8_parts_of_15(self):
        self.answer_up_to(15)                    # screening + part 1

        page = self.client.get(self.url(16))

        self.assertContains(page, 'Part 2 of 8')
        self.assertContains(page, 'Question 1 of 15')
        self.assertContains(page, 'Q16.')

    def test_other_box_on_choice_questions_but_not_the_screening_question(self):
        self.assertNotContains(self.client.get(self.url(0)), 'Other (please specify)')
        self.answer(0)
        page = self.client.get(self.url(1))
        self.assertContains(page, 'Other (please specify)')

        question = self.questions[1]
        missing = self.client.post(self.url(1), {f'question_{question.id}': '__other__'})
        self.assertContains(missing, 'Please type your')
        self.client.post(self.url(1), {f'question_{question.id}': '__other__',
                                       f'question_{question.id}_other': 'Drive-through only'})
        answer = Answer.objects.get(response__user=self.user, question=question)
        self.assertEqual((answer.text_answer, answer.selected_choices.count()), ('Drive-through only', 0))
        self.assertContains(self.client.get(self.url(1)), 'Drive-through only')

    def test_timer_adds_time_per_question_and_is_kept(self):
        self.answer(0, {'elapsed_seconds': '40'})
        self.answer(1, {'elapsed_seconds': '99999'})                              # idle tab: capped at 30 min

        response = SurveyResponse.objects.get(user=self.user)
        self.assertEqual(response.time_spent_seconds, 40 + 30 * 60)
        self.assertContains(self.client.get(self.url(2)), f'data-start="{40 + 30 * 60}"')

    def test_quick_draw_every_30_questions_screening_not_counted(self):
        self.answer_up_to(29)                    # screening + 29 questions
        progress = LuckyDrawView().quick_draw_progress(self.user)
        self.assertEqual((progress['plays'], progress['remaining']), (0, 1))
        self.assertContains(self.client.get(self.url(30)), '1 more question to your next Quick draw play')

        self.answer(30)
        self.assertEqual(LuckyDrawView().quick_draw_progress(self.user)['plays'], 1)
        self.assertContains(self.client.get(self.url(31)), 'id="quick-draw-unlocked"')

    def test_answering_again_does_not_count_twice(self):
        self.answer_up_to(5)
        self.answer(3)

        self.assertEqual(LuckyDrawView().quick_draw_progress(self.user)['answered_total'], 5)

    def test_finished_category_counts_one_survey_and_gives_4_quick_draw_plays(self):
        self.answer_up_to(MAIN_QUESTIONS - 1)
        last = self.answer(MAIN_QUESTIONS)

        self.assertRedirects(last, reverse('surveys:survey_complete', args=[self.survey.id]), fetch_redirect_response=False)
        response = SurveyResponse.objects.get(user=self.user, survey=self.survey)
        self.assertIsNotNone(response.completed_at)
        self.assertEqual(UserSurveyProgress.objects.get(user=self.user).completed_count, 1)
        eligibility = LuckyDrawView().get_eligibility_context(self.user)
        self.assertEqual((eligibility['survey_plays_available'], eligibility['total_surveys']), (4, 1))
        # ...and the other category is open again.
        self.assertEqual(self.client.get(reverse('surveys:survey_detail', args=[self.other_survey.id])).status_code, 200)

    def test_a_quick_draw_play_uses_30_questions(self):
        self.answer_up_to(60)                    # 60 questions -> 2 plays
        LuckyDrawEntry.objects.create(user=self.user, draw_type='survey', guessed_number=1, winning_number=2,
                                      surveys_at_play=30)

        progress = LuckyDrawView().quick_draw_progress(self.user)
        self.assertEqual((progress['plays'], progress['answered_since']), (1, 30))


@override_settings(SURVEY_CONFIG=SURVEY_CONFIG, LUCKY_DRAW_CONFIG=DRAW_CONFIG)
class ContinueWhereYouLeftOffTests(SurveyPartsBase):
    """Session management: the survey continues where the user left it, across
    logout/login, a new browser session or another device."""

    def test_resumes_after_logging_out_and_back_in(self):
        self.answer_up_to(6)
        self.client.logout()                                  # session gone

        self.client.force_login(get_user_model().objects.get(pk=self.user.pk))   # new session
        resume = self.client.get(reverse('surveys:survey_detail', args=[self.survey.id]), follow=True)

        self.assertEqual(resume.redirect_chain[-1][0], self.url(7))
        self.assertContains(resume, 'continuing where you left off')

    def test_login_goes_straight_back_into_the_unfinished_survey(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from surveys.views_frontend import CustomLoginView
        self.answer_up_to(2)

        request = RequestFactory().get('/login/')
        request.user = get_user_model().objects.get(pk=self.user.pk)
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        view = CustomLoginView()
        view.request = request

        self.assertEqual(str(view.get_success_url()), reverse('surveys:survey_detail', args=[self.survey.id]))

    def test_login_goes_to_the_dashboard_with_nothing_unfinished(self):
        from django.test import RequestFactory
        from surveys.views_frontend import CustomLoginView
        request = RequestFactory().get('/login/')
        request.user = self.user
        view = CustomLoginView()
        view.request = request

        self.assertEqual(str(view.get_success_url()), reverse('surveys:dashboard'))

    def test_category_pages_say_continue_and_finish_first(self):
        self.answer_up_to(2)

        own = self.client.get(reverse('surveys:category_detail', args=[self.survey.category.slug]))
        other = self.client.get(reverse('surveys:category_detail', args=[self.other_survey.category.slug]))

        self.assertContains(own, 'Continue where you left off')
        self.assertContains(other, 'Finish your Fast Food survey first')
        self.assertContains(other, 'id="continue-survey-banner"')
        self.assertNotContains(other, 'Start Survey')
