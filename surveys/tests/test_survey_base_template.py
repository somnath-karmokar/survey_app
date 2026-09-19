"""Pages built on the survey base template load Bootstrap's JavaScript exactly once.

Two copies each handle the same click on a `data-bs-toggle="dropdown"` button: the
first opens the menu and the second closes it again, so the profile menu never
appears while taking a survey or poll.
"""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import Country, Question, Survey, SurveyCategory


def bootstrap_script_tags(html):
    """Every <script src> that loads Bootstrap's JS, from any CDN or static path."""
    return re.findall(r'<script[^>]+src="[^"]*bootstrap[^"]*\.js"', html)


class SurveyBaseTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(name='United States', code='US')
        cls.user = get_user_model().objects.create_user(
            username='base@example.com', email='base@example.com', password='pw', first_name='Dee',
        )
        cls.user.profile.country = cls.country
        cls.user.profile.save(update_fields=['country'])
        category = SurveyCategory.objects.create(name='Category', country=cls.country)
        cls.survey = Survey.objects.create(name='Ongoing survey', category=category, is_active=True)
        question = Question.objects.create(question_text='Q1', question_type='text', order=0)
        question.surveys.add(cls.survey)

    def setUp(self):
        self.client.force_login(self.user)

    def test_bootstrap_js_is_loaded_once_on_survey_pages(self):
        pages = {
            'survey question (survey in progress)': reverse('surveys:survey_question', args=[self.survey.id, 0]),
            'survey list': reverse('surveys:survey_list'),
        }
        for name, url in pages.items():
            with self.subTest(page=name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn('id="userDropdown"', html)  # the profile menu is on the page
                self.assertEqual(len(bootstrap_script_tags(html)), 1, bootstrap_script_tags(html))
