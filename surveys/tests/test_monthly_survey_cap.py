"""Every user can complete at most SURVEY_CONFIG['MONTHLY_SURVEY_CAP'] surveys a
calendar month; at the limit they can neither start nor finish another."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.models import Country, Question, Survey, SurveyCategory, SurveyResponse

CAP = 5
BANNER_MARKER = 'fa-hourglass-half'   # only the "monthly limit reached" banner uses this icon


def survey_config(cap):
    return {**settings.SURVEY_CONFIG, 'MONTHLY_SURVEY_CAP': cap}


@override_settings(SURVEY_CONFIG=survey_config(CAP))
class MonthlySurveyCapTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='cap@example.com', email='cap@example.com', password='pw',
        )
        self.country = Country.objects.create(name='United States', code='US')
        self.user.profile.country = self.country
        self.user.profile.save(update_fields=['country'])
        self.category = SurveyCategory.objects.create(name='General', country=self.country)
        self.survey = Survey.objects.create(name='A survey', category=self.category, is_active=True)
        question = Question.objects.create(question_text='Q?', question_type='text', order=0)
        question.surveys.add(self.survey)
        self.client.force_login(self.user)

    def complete(self, count, when=None):
        """Record `count` completed surveys for the user, at `when` (default: now)."""
        when = when or timezone.now()
        other = Survey.objects.create(name='Filler', category=SurveyCategory.objects.create(
            name=f'Filler {SurveyResponse.objects.count()}', country=self.country), is_active=True)
        SurveyResponse.objects.bulk_create(
            [SurveyResponse(user=self.user, survey=other, completed_at=when) for _ in range(count)]
        )

    def test_one_below_the_cap_is_still_allowed(self):
        self.complete(CAP - 1)

        can_take, _ = self.survey.can_user_take_survey(self.user)

        self.assertTrue(can_take)

    def test_at_the_cap_is_blocked_with_a_reason(self):
        self.complete(CAP)

        can_take, message = self.survey.can_user_take_survey(self.user)

        self.assertFalse(can_take)
        self.assertIn(f"limit of {CAP} surveys", message)

    def test_last_months_surveys_do_not_count(self):
        last_month = timezone.now().replace(day=1) - timedelta(days=3)
        self.complete(CAP + 10, when=last_month)

        can_take, _ = self.survey.can_user_take_survey(self.user)

        self.assertTrue(can_take)

    def test_unfinished_surveys_do_not_count(self):
        SurveyResponse.objects.bulk_create(
            [SurveyResponse(user=self.user, survey=self.survey, completed_at=None) for _ in range(CAP + 3)]
        )

        self.assertTrue(self.survey.can_user_take_survey(self.user)[0])

    @override_settings(SURVEY_CONFIG=survey_config(None))
    def test_no_cap_configured_means_no_limit(self):
        self.complete(CAP * 10)

        self.assertTrue(self.survey.can_user_take_survey(self.user)[0])
        self.assertIsNone(SurveyResponse.monthly_limit_status(self.user))

    def test_status_reports_progress_and_reset_date(self):
        self.complete(2)

        status = SurveyResponse.monthly_limit_status(self.user)

        self.assertEqual((status['cap'], status['completed'], status['remaining']), (CAP, 2, CAP - 2))
        self.assertFalse(status['reached'])
        self.assertEqual(status['resets_on'].day, 1)
        self.assertGreater(status['resets_on'], timezone.now())

    def test_capped_user_is_redirected_and_no_response_is_saved(self):
        self.complete(CAP)
        before = SurveyResponse.objects.filter(user=self.user).count()
        question = self.survey.questions.get()

        response = self.client.post(
            reverse('surveys:survey_question', args=[self.survey.id, 0]),
            {f'question_{question.id}': 'an answer'},
            follow=True,
        )

        self.assertEqual(SurveyResponse.objects.filter(user=self.user).count(), before)
        self.assertEqual(
            response.redirect_chain[-1][0],
            reverse('surveys:category_detail', args=[self.category.slug]),
        )
        self.assertContains(response, f"limit of {CAP} surveys")

    def test_banner_only_shows_once_the_cap_is_reached(self):
        self.complete(CAP - 1)
        self.assertNotContains(self.client.get(reverse('surveys:survey_list')), BANNER_MARKER)

        self.complete(1)
        self.assertContains(self.client.get(reverse('surveys:survey_list')), BANNER_MARKER)
