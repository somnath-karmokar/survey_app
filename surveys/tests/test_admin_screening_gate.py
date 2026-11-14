"""Admin: the Screening Gate questions page and the clearer menu names."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import Choice, Country, Question, ScreeningQuestion, Survey, SurveyCategory


class ScreeningGateAdminTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser('admin@sudraw.com', 'admin@sudraw.com', 'pw')
        self.client.force_login(admin)
        uk = Country.objects.create(name='United Kingdom', code='GB')
        self.fast_food = Survey.objects.create(name='Fast Food Chains',
                                               category=SurveyCategory.objects.create(name='Fast Food Chains', country=uk))
        self.cinema = Survey.objects.create(name='Cinema', category=SurveyCategory.objects.create(name='Cinema', country=uk))
        self.gate = Question.objects.create(question_text='Which fast food chains have you visited?',
                                            question_type='multiple_choice', order=0, not_listed_label='fast food chain')
        self.gate.surveys.add(self.fast_food)
        Choice.objects.create(question=self.gate, choice_text='KFC')
        Choice.objects.create(question=self.gate, choice_text='Foodie', is_disqualifying=True)
        part_question = Question.objects.create(question_text='How fast was your order?', question_type='single_choice', order=1)
        part_question.surveys.add(self.fast_food)

    def add(self, survey, options):
        data = {'survey': survey.id, 'question_text': 'Which cinemas have you been to?', 'not_listed_label': 'cinema chain',
                'choices-TOTAL_FORMS': str(len(options)), 'choices-INITIAL_FORMS': '0',
                'choices-MIN_NUM_FORMS': '0', 'choices-MAX_NUM_FORMS': '1000'}
        for i, (text, red) in enumerate(options):
            data[f'choices-{i}-choice_text'] = text
            if red:
                data[f'choices-{i}-is_disqualifying'] = 'on'
        return self.client.post(reverse('admin:surveys_screeningquestion_add'), data)

    def test_dashboard_links_to_screening_gate_questions(self):
        page = self.client.get(reverse('admin:index'))
        self.assertContains(page, 'Screening Gate questions')
        self.assertContains(page, reverse('admin:surveys_screeningquestion_changelist'))

    def test_list_shows_only_screening_questions_with_survey_and_red_options(self):
        page = self.client.get(reverse('admin:surveys_screeningquestion_changelist'))

        self.assertContains(page, 'Which fast food chains have you visited?')
        self.assertContains(page, 'United Kingdom')
        self.assertContains(page, 'Foodie')
        self.assertContains(page, 'fast food chain')
        self.assertNotContains(page, 'How fast was your order?')

    def test_edit_page_explains_the_untruthful_tick_box(self):
        page = self.client.get(reverse('admin:surveys_screeningquestion_change', args=[self.gate.pk]))

        self.assertContains(page, 'Untruthful (red)')
        self.assertContains(page, 'suspends the user for 7 days')
        self.assertContains(page, 'Type-your-own box asks for')

    def test_add_a_screening_gate_to_a_survey(self):
        response = self.add(self.cinema, [('Odeon', False), ('Britannia Theatres', True), ('None of the above', True)])

        self.assertEqual(response.status_code, 302)
        gate = ScreeningQuestion.objects.get(surveys=self.cinema)
        self.assertEqual((gate.order, gate.question_type, gate.not_listed_label), (0, 'multiple_choice', 'cinema chain'))
        self.assertEqual(sorted(gate.choices.filter(is_disqualifying=True).values_list('choice_text', flat=True)),
                         ['Britannia Theatres', 'None of the above'])

    def test_needs_an_untruthful_option(self):
        response = self.add(self.cinema, [('Odeon', False), ('Vue', False)])

        self.assertContains(response, 'Tick &quot;Untruthful (red)&quot; on at least one option')
        self.assertFalse(Question.objects.filter(surveys=self.cinema).exists())

    def test_one_screening_gate_per_survey(self):
        response = self.add(self.fast_food, [('Odeon', False), ('Fake', True)])

        self.assertContains(response, 'already has a Screening Gate question')

    def test_clearer_menu_names(self):
        page = self.client.get(reverse('admin:index')).content.decode()
        for name in ('Answer options', 'Draw plays &amp; results', 'Withdrawal requests',
                     'Country settings (prizes, rewards, limits)', 'Suspensions (untruthful answers)'):
            self.assertIn(name, page)
