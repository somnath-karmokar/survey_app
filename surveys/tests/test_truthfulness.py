"""New Enterprise Surveys: import from Word, and untruthful answers.

Picking a red (untruthful) option ends the survey and suspends the user from
surveys and draws for 7 days.
"""
import datetime
import json
import os
import shutil
import tempfile
from decimal import Decimal
from io import StringIO
from unittest import mock

import docx
from docx.shared import RGBColor
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from surveys.models import (
    Choice, Country, LuckyDrawEntry, Question, Survey, SurveyCategory, SurveyResponse, SurveySuspension, UserProfile,
    UserSurveyProgress, WalletTransaction,
)
from surveys.survey_import import parse_document

RED = RGBColor(0xFF, 0x00, 0x00)
DARK_RED = RGBColor(0x98, 0x00, 0x00)
GREEN = RGBColor(0x38, 0x76, 0x1D)


def write_survey_doc(path, brand='Burger Place'):
    """A small document in the real layout: screening + 3 questions + trailing notes."""
    d = docx.Document()
    d.add_paragraph('Screening Gate (Mandatory)')
    d.add_paragraph('S01. Which of the following fast food chains have you visited in the past 3 months?')
    d.add_paragraph(brand)
    d.add_paragraph('KFC')
    d.add_paragraph().add_run('Foodie').font.color.rgb = RED
    d.add_paragraph().add_run('Burgerama').font.color.rgb = DARK_RED
    d.add_paragraph().add_run('[Insert Your Target Local Fast Food Chain]').font.color.rgb = GREEN
    p = d.add_paragraph()
    p.add_run('None of the above ').font.color.rgb = RED
    p.add_run('(If selected, terminate survey)').font.color.rgb = RED
    d.add_paragraph('Part 1: Customer Satisfaction Index (CSI)')
    d.add_paragraph('1. 📈 Customer Satisfaction Index (CSI)')
    d.add_paragraph('Q01. Order Speed')
    d.add_paragraph('How fast was your order ready?')
    d.add_paragraph('⏱️ Under 3 minutes.')
    d.add_paragraph('⏱️ Over 10 minutes.')
    d.add_paragraph('Q02. Recommend')
    d.add_paragraph('How likely are you to recommend this chain?')
    d.add_paragraph('Provide standard numerical radio buttons from 0 (Not at all likely) to 10 (Extremely likely).')
    d.add_paragraph('Q03. Slogan Recall')
    d.add_paragraph('Can you write down their slogan?')
    d.add_paragraph('Provide an open text entry box to capture unaided recall.')
    d.add_heading('Important scoring recommendations', level=2)
    d.add_paragraph('Analyse switching separately from intentions.')
    d.save(path)


class ParserTests(TestCase):
    def test_reads_screening_questions_scale_text_and_skips_notes(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, ' Fast Food Chains - Ready.docx')
        write_survey_doc(path)

        doc = parse_document(path)

        self.assertEqual(doc['name'], 'Fast Food Chains')
        self.assertEqual(doc['warnings'], [])
        screening = doc['screening']
        self.assertEqual(screening['type'], 'multiple_choice')
        self.assertEqual([(o['text'], o['red']) for o in screening['options']],
                         [('Burger Place', False), ('KFC', False), ('Foodie', True), ('Burgerama', True),
                          ('None of the above', True)])
        self.assertEqual(screening['not_listed_label'], 'fast food chain')            # the green line
        self.assertEqual([q['type'] for q in doc['questions']], ['single_choice', 'single_choice', 'text'])
        scale = [o['text'] for o in doc['questions'][1]['options']]
        self.assertEqual((len(scale), scale[0], scale[-1]), (11, '0 (Not at all likely)', '10 (Extremely likely)'))
        self.assertEqual(doc['questions'][0]['options'][-1]['text'], 'Over 10 minutes.')     # notes not swallowed, emoji removed


class ReplaceSurveysCommandTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.us = Country.objects.create(name='United States', code='US')
        self.source = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source)
        for country, brand in (('UK', 'Burger Place'), ('USA', 'Burger Spot')):
            os.makedirs(os.path.join(self.source, f'New Enterprise Surveys - {country}'))
            write_survey_doc(os.path.join(self.source, f'New Enterprise Surveys - {country}', 'Fast Food Chains - Ready.docx'), brand)

        old_category = SurveyCategory.objects.create(name='Old Category', country=self.uk)
        old_survey = Survey.objects.create(name='Old Survey', category=old_category)
        old_question = Question.objects.create(question_text='Old?', question_type='single_choice')
        old_question.surveys.add(old_survey)
        Choice.objects.create(question=old_question, choice_text='Yes')
        self.user = get_user_model().objects.create_user(username='u@example.com', email='u@example.com', password='pw')
        self.user.profile.country = self.uk
        self.user.profile.save()
        SurveyResponse.objects.create(user=self.user, survey=old_survey, completed_at=timezone.now())
        UserSurveyProgress.objects.create(user=self.user, category=old_category, level=1, completed_count=7)
        UserProfile.objects.filter(user=self.user).update(wallet_balance=Decimal('12.00'))

    def test_dry_run_changes_nothing(self):
        out = StringIO()
        call_command('replace_surveys', source=self.source, stdout=out)

        self.assertIn('Dry run only', out.getvalue())
        self.assertTrue(SurveyCategory.objects.filter(name='Old Category').exists())

    def test_replaces_old_surveys_and_resets_users(self):
        call_command('replace_surveys', source=self.source, confirm=True, stdout=StringIO())

        self.assertFalse(SurveyCategory.objects.filter(name='Old Category').exists())
        self.assertFalse(SurveyResponse.objects.exists())
        self.assertFalse(UserSurveyProgress.objects.exists())
        self.assertEqual(UserProfile.objects.get(user=self.user).wallet_balance, Decimal('0.00'))

        categories = SurveyCategory.objects.order_by('country__code')
        self.assertEqual([(c.name, str(c.country.code)) for c in categories],
                         [('Fast Food Chains', 'GB'), ('Fast Food Chains', 'US')])
        survey = Survey.objects.get(category__country=self.uk)
        questions = list(survey.questions.order_by('order'))
        self.assertEqual(len(questions), 4)                                     # screening + 3
        self.assertEqual(questions[0].question_type, 'multiple_choice')
        self.assertEqual(sorted(questions[0].choices.filter(is_disqualifying=True).values_list('choice_text', flat=True)),
                         ['Burgerama', 'Foodie', 'None of the above'])
        self.assertEqual(questions[0].not_listed_label, 'fast food chain')
        self.assertEqual((questions[1].topic, questions[1].question_text), ('Order Speed', 'How fast was your order ready?'))
        self.assertIsNone(questions[0].topic)                                   # screening has no topic
        self.assertEqual(questions[2].choices.count(), 11)
        self.assertEqual(questions[3].question_type, 'text')


class UntruthfulAnswerTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        category = SurveyCategory.objects.create(name='Fast Food Chains', country=self.uk)
        self.survey = Survey.objects.create(name='Fast Food Chains', category=category, level=1)
        self.screening = Question.objects.create(question_text='Which have you visited?',
                                                 question_type='multiple_choice', order=0, not_listed_label='fast food chain')
        self.screening.surveys.add(self.survey)
        self.real = Choice.objects.create(question=self.screening, choice_text='KFC')
        self.fake = Choice.objects.create(question=self.screening, choice_text='Foodie', is_disqualifying=True)
        second = Question.objects.create(question_text='How fast?', question_type='single_choice', order=1)
        second.surveys.add(self.survey)
        Choice.objects.create(question=second, choice_text='Fast')
        self.user = get_user_model().objects.create_user(username='t@example.com', email='t@example.com', password='pw')
        self.user.profile.country = self.uk
        self.user.profile.save()
        self.client.force_login(self.user)

    def answer_screening(self, *choices, other=None):
        data = {f'question_{self.screening.id}': [str(c.id) for c in choices]}
        if other is not None:
            data[f'question_{self.screening.id}_other'] = other
        return self.client.post(reverse('surveys:survey_question', args=[self.survey.id, 0]), data, follow=True)

    def test_untruthful_answer_ends_survey_and_suspends_for_7_days(self):
        response = self.answer_screening(self.real, self.fake)

        self.assertContains(response, 'Your account has been suspended for 7 days for not being truthful.')
        self.assertEqual(response.redirect_chain[-1][0], reverse('surveys:user_profile'))
        profile = UserProfile.objects.get(user=self.user)
        self.assertTrue(profile.is_suspended)
        self.assertAlmostEqual(profile.suspended_until, timezone.now() + datetime.timedelta(days=7),
                               delta=datetime.timedelta(minutes=1))
        self.assertFalse(SurveyResponse.objects.exists())
        self.assertNotIn(f'survey_{self.survey.id}_answers', self.client.session)

    def test_truthful_answer_carries_on(self):
        response = self.answer_screening(self.real)

        self.assertEqual(response.redirect_chain[-1][0],
                         reverse('surveys:survey_question', args=[self.survey.id, 1]))
        self.assertFalse(UserProfile.objects.get(user=self.user).is_suspended)

    def test_suspended_user_cannot_start_surveys_or_play_draws(self):
        self.answer_screening(self.fake)

        page = self.client.get(reverse('surveys:survey_detail', args=[self.survey.id]), follow=True)
        self.assertContains(page, 'suspended for 7 days for not being truthful')

        draw = self.client.post(reverse('surveys:lucky_draw'), data=json.dumps({'index': 0, 'draw_type': 'survey'}),
                                content_type='application/json')
        self.assertEqual(draw.status_code, 400)
        self.assertIn('suspended', draw.json()['error'])
        self.assertContains(self.client.get(reverse('surveys:lucky_draw')), 'id="suspension-notice"')

    def test_suspension_lifts_after_7_days(self):
        self.answer_screening(self.fake)
        later = timezone.now() + datetime.timedelta(days=7, minutes=5)

        with mock.patch('django.utils.timezone.now', return_value=later):
            can_take, message = self.survey.can_user_take_survey(get_user_model().objects.get(pk=self.user.pk))

        self.assertTrue(can_take, message)

    def test_suspension_is_recorded_and_explained_on_the_profile(self):
        self.answer_screening(self.real, self.fake, other='Burger Barn')

        record = SurveySuspension.objects.get(user=self.user)
        self.assertEqual((record.category_name, record.untruthful_list), ('Fast Food Chains', ['Foodie']))
        self.assertEqual(record.selected_list, ['KFC', 'Foodie', 'Burger Barn (typed in)'])
        profile = self.client.get(reverse('surveys:user_profile'))
        self.assertContains(profile, 'id="suspension-details"')
        self.assertContains(profile, 'Which have you visited?')
        self.assertContains(profile, '&ldquo;Foodie&rdquo;')
        self.assertContains(self.client.get(reverse('surveys:dashboard')), 'id="dashboard-suspension"')

    def test_screening_page_has_the_not_listed_box_and_hides_which_options_are_untruthful(self):
        page = self.client.get(reverse('surveys:survey_question', args=[self.survey.id, 0]))

        self.assertContains(page, 'id="screening-gate"')
        self.assertContains(page, 'Not listed? Type the name of the fast food chain you use')
        self.assertContains(page, 'placeholder="e.g. your local fast food chain"')
        self.assertNotContains(page, 'value="__other__"')                         # no tick needed
        self.assertNotContains(page, 'disqualif')

    def test_typing_an_unlisted_answer_carries_on(self):
        response = self.answer_screening(other='Burger Barn')

        self.assertEqual(response.redirect_chain[-1][0], reverse('surveys:survey_question', args=[self.survey.id, 1]))
        self.assertFalse(UserProfile.objects.get(user=self.user).is_suspended)
        answer = SurveyResponse.objects.get(user=self.user).answers.get(question=self.screening)
        self.assertEqual(answer.text_answer, 'Burger Barn')

    def test_suspended_user_starting_a_survey_is_told_they_are_suspended(self):
        self.answer_screening(self.fake)

        for url in (reverse('surveys:survey_detail', args=[self.survey.id]),
                    reverse('surveys:take_survey', args=[self.survey.id])):        # old Start Survey link
            page = self.client.get(url, follow=True)
            self.assertEqual(page.redirect_chain[-1][0],
                             reverse('surveys:category_detail', args=[self.survey.category.slug]))
            self.assertContains(page, "You can&#x27;t take surveys until")
            self.assertContains(page, 'id="suspension-banner"')
            self.assertContains(page, 'Suspended')
            self.assertNotContains(page, 'Start Survey')
        self.assertContains(self.client.get(reverse('surveys:survey_list')), 'id="suspension-banner"')

    def test_start_buttons_open_the_new_survey_flow(self):
        page = self.client.get(reverse('surveys:category_detail', args=[self.survey.category.slug]))

        self.assertContains(page, reverse('surveys:survey_detail', args=[self.survey.id]))
        self.assertNotContains(page, reverse('surveys:take_survey', args=[self.survey.id]))
        self.assertNotContains(page, 'id="suspension-banner"')

    def test_must_tick_an_option_or_type_one(self):
        response = self.client.post(reverse('surveys:survey_question', args=[self.survey.id, 0]), {})

        self.assertContains(response, 'Please select at least one option, or type yours in the box below.')
        self.assertFalse(SurveyResponse.objects.exists())


    def test_admin_can_lift_a_suspension(self):
        self.answer_screening(self.fake)

        SurveySuspension.objects.get(user=self.user).lift()

        self.assertFalse(UserProfile.objects.get(user=self.user).is_suspended)
        self.assertEqual(self.client.get(reverse('surveys:survey_detail', args=[self.survey.id])).status_code, 200)


class SyncScreeningCommandTests(TestCase):
    def test_marks_missed_untruthful_options_and_turns_on_the_box_without_touching_users(self):
        Country.objects.create(name='United Kingdom', code='GB')
        source = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, source)
        os.makedirs(os.path.join(source, 'New Enterprise Surveys - UK'))
        write_survey_doc(os.path.join(source, 'New Enterprise Surveys - UK', 'Fast Food Chains - Ready.docx'))
        call_command('replace_surveys', source=source, confirm=True, stdout=StringIO())
        screening = Question.objects.get(order=0)
        Choice.objects.filter(choice_text='Burgerama').update(is_disqualifying=False)     # as imported before the fix
        Question.objects.filter(pk=screening.pk).update(not_listed_label='')
        user = get_user_model().objects.create_user(username='s@example.com', email='s@example.com', password='pw')
        SurveyResponse.objects.create(user=user, survey=Survey.objects.get())

        call_command('sync_screening_questions', source=source, confirm=True, stdout=StringIO())

        self.assertTrue(Choice.objects.get(choice_text='Burgerama').is_disqualifying)
        self.assertEqual(Question.objects.get(pk=screening.pk).not_listed_label, 'fast food chain')
        self.assertEqual(SurveyResponse.objects.count(), 1)


class NotListedLabelTests(TestCase):
    def test_label_follows_the_category_not_the_documents_copy_paste(self):
        from surveys.survey_import import not_listed_label
        self.assertEqual(not_listed_label('Airlines', '[Insert Your Target Local Independent Gym / CrossFit Box]'), 'airline')
        self.assertEqual(not_listed_label('Pharmacies & Health Retail', '[Insert Your Target Local Cinema Chain]'), 'pharmacy')
        self.assertEqual(not_listed_label('Something New', '[Insert Your Target Local Pizza Place]'), 'pizza place')


class ScreeningGateLayoutTests(TestCase):
    """The type-your-own box is always there, and the screening step shows no index number."""

    def setUp(self):
        uk = Country.objects.create(name='United Kingdom', code='GB')
        category = SurveyCategory.objects.create(name='Fast Food Chains', country=uk)
        self.survey = Survey.objects.create(name='Fast Food Chains', category=category)
        self.screening = Question.objects.create(question_text='Which have you visited?',
                                                 question_type='multiple_choice', order=0)   # no wording set
        self.screening.surveys.add(self.survey)
        Choice.objects.create(question=self.screening, choice_text='KFC')
        Choice.objects.create(question=self.screening, choice_text='Foodie', is_disqualifying=True)
        q1 = Question.objects.create(question_text='How fast?', question_type='single_choice', order=1)
        q1.surveys.add(self.survey)
        Choice.objects.create(question=q1, choice_text='Fast')
        user = get_user_model().objects.create_user(username='g@example.com', email='g@example.com', password='pw')
        user.profile.country = uk
        user.profile.save()
        self.client.force_login(user)

    def test_box_shown_even_without_category_wording(self):
        page = self.client.get(reverse('surveys:survey_question', args=[self.survey.id, 0]))

        self.assertContains(page, 'Not listed? Type the name of the brand you use')
        self.assertContains(page, 'not-listed-input')

    def test_no_index_number_on_the_screening_step(self):
        page = self.client.get(reverse('surveys:survey_question', args=[self.survey.id, 0]))

        self.assertNotContains(page, 'overall')
        self.assertNotContains(page, '1 / 2')
        self.assertContains(page, '<title>Fast Food Chains - Screening Gate</title>', html=False)

    def test_main_questions_still_show_their_position(self):
        self.client.post(reverse('surveys:survey_question', args=[self.survey.id, 0]),
                         {f'question_{self.screening.id}': [str(self.screening.choices.get(choice_text='KFC').id)]})
        page = self.client.get(reverse('surveys:survey_question', args=[self.survey.id, 1]))

        self.assertContains(page, '1 / 1 overall')
