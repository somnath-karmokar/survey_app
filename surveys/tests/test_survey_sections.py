"""Survey sections (the 8 parts) and emoji removal in the Word import."""
import os
import shutil
import tempfile
from io import StringIO

import docx
from docx.shared import RGBColor
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from surveys.models import Answer, Choice, Country, Question, Survey, SurveyCategory, SurveyResponse
from surveys.survey_import import SECTIONS, parse_document, section_index, strip_emojis

RED = RGBColor(0xFF, 0x00, 0x00)


def question(d, number, title, options):
    d.add_paragraph(f'Q{number:02d}. {title}')
    d.add_paragraph(f'Question {number} text?')
    for option in options:
        d.add_paragraph(option)


def write_doc(path):
    """Headings in every style the real documents use, one with no heading at all (section 3)."""
    d = docx.Document()
    d.add_paragraph('Screening Gate (Mandatory)')
    d.add_paragraph('S01. Which of these have you used?')
    d.add_paragraph('Real Brand')
    d.add_paragraph().add_run('Fake Brand').font.color.rgb = RED
    d.add_paragraph('Part 1: Customer Satisfaction Index (CSI) & Brand Reputation Ranking')
    d.add_paragraph('1. 📈 Customer Satisfaction Index (CSI)')
    d.add_paragraph('Measures day-to-day transactional efficiency.')                 # note under the heading
    question(d, 1, '⏱️ Order Speed', ['⏱️ Under 3 minutes.', '⏱️ Over 10 minutes.'])
    question(d, 2, 'Staff', ['🙂 Friendly', '😠 Rude'])
    d.add_paragraph('🛡️ 2. BRAND REPUTATION RANKING')                                 # right after options
    d.add_paragraph('Home & White Goods Retailers')                                   # stray line
    question(d, 3, 'Trust', ['High', 'Low'])
    question(d, 4, 'Ethics', ['Good', 'Bad'])
    question(d, 5, 'Recommend', ['Yes', 'No'])                                        # section 3: no heading
    question(d, 6, 'Promote', ['Yes', 'No'])
    d.add_paragraph('Index 4 — Customer Loyalty Benchmark')
    d.add_paragraph('Q46–Q60 · Focus: repeat purchases')
    question(d, 7, 'Return', ['Yes', 'No'])
    question(d, 8, 'Stay', ['Yes', 'No'])
    d.save(path)


class ParserSectionTests(TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.path = os.path.join(self.folder, 'Retail - Ready.docx')
        write_doc(self.path)
        self.doc = parse_document(self.path)

    def test_every_heading_style_is_recognised(self):
        self.assertEqual(section_index('1. 📈 Customer Satisfaction Index (CSI)'), 0)
        self.assertEqual(section_index('🛡️ 2. BRAND REPUTATION RANKING'), 1)
        self.assertEqual(section_index('Index 3 — Net Promoter Score (NPS) Benchmark'), 2)
        self.assertEqual(section_index('👓 INDEX 1 — Customer Satisfaction Index (CSI) for Opticians (Questions 1–15)'), 0)
        self.assertEqual(section_index('🔄 8. Switching Behaviour Report'), 7)
        self.assertIsNone(section_index('Customer satisfaction was high; staff were friendly.'))
        self.assertIsNone(section_index('Royal Caribbean International'))

    def test_questions_get_their_section_and_a_missing_heading_is_filled_in(self):
        sections = [q['section'] for q in self.doc['questions']]
        self.assertEqual(sections, [SECTIONS[0][0]] * 2 + [SECTIONS[1][0]] * 2 + [SECTIONS[2][0]] * 2 + [SECTIONS[3][0]] * 2)

    def test_headings_and_their_notes_are_never_answer_options(self):
        options = [o['text'] for q in self.doc['questions'] for o in q['options']]
        self.assertEqual(self.doc['questions'][1]['options'], [{'text': 'Friendly', 'red': False}, {'text': 'Rude', 'red': False}])
        for junk in ('BRAND REPUTATION', 'Home & White Goods', 'Loyalty Benchmark', 'Q46–Q60', 'Measures day-to-day'):
            self.assertFalse(any(junk in o for o in options), junk)

    def test_emojis_removed_from_titles_and_options(self):
        q1 = self.doc['questions'][0]
        self.assertEqual(q1['title'], 'Order Speed')
        self.assertEqual([o['text'] for o in q1['options']], ['Under 3 minutes.', 'Over 10 minutes.'])
        self.assertEqual(strip_emojis('🍽️ Elite execution; hot dishes ✅'), 'Elite execution; hot dishes')


class SyncSurveyContentTests(TestCase):
    """Surveys imported before the fix are corrected in place; answers are kept."""

    def setUp(self):
        self.source = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source)
        os.makedirs(os.path.join(self.source, 'New Enterprise Surveys - UK'))
        write_doc(os.path.join(self.source, 'New Enterprise Surveys - UK', 'Retail - Ready.docx'))
        uk = Country.objects.create(name='United Kingdom', code='GB')
        self.survey = Survey.objects.create(name='Retail', category=SurveyCategory.objects.create(name='Retail', country=uk))
        # As the old importer stored it: emojis kept, headings swallowed as options, no sections.
        old = [('Which of these have you used?', ['Real Brand', 'Fake Brand']),
               ('⏱️ Order Speed\nQuestion 1 text?', ['⏱️ Under 3 minutes.', '⏱️ Over 10 minutes.']),
               ('Staff\nQuestion 2 text?', ['🙂 Friendly', '😠 Rude', '🛡️ 2. BRAND REPUTATION RANKING', 'Home & White Goods Retailers'])]
        old += [(f'{t}\nQuestion {n} text?', o) for n, t, o in (
            (3, 'Trust', ['High', 'Low']), (4, 'Ethics', ['Good', 'Bad']), (5, 'Recommend', ['Yes', 'No']),
            (6, 'Promote', ['Yes', 'No', 'Index 4 — Customer Loyalty Benchmark', 'Q46–Q60 · Focus: repeat purchases']),
            (7, 'Return', ['Yes', 'No']), (8, 'Stay', ['Yes', 'No']))]
        self.questions = []
        for order, (text, options) in enumerate(old):
            q = Question.objects.create(question_text=text, question_type='multiple_choice' if order == 0 else 'single_choice', order=order)
            q.surveys.add(self.survey)
            for option in options:
                Choice.objects.create(question=q, choice_text=option, is_disqualifying=(option == 'Fake Brand'))
            self.questions.append(q)
        user = get_user_model().objects.create_user('a@example.com', 'a@example.com', 'pw')
        self.response = SurveyResponse.objects.create(user=user, survey=self.survey)
        self.answer = Answer.objects.create(response=self.response, question=self.questions[1])
        self.answer.selected_choices.set([self.questions[1].choices.get(choice_text='⏱️ Under 3 minutes.')])

    def test_dry_run_changes_nothing(self):
        out = StringIO()
        call_command('sync_survey_content', source=self.source, stdout=out)

        self.assertIn('Answer options to delete (they were headings/notes): 4', out.getvalue())
        self.assertTrue(Choice.objects.filter(choice_text__contains='BRAND REPUTATION').exists())

    def test_corrects_in_place_and_keeps_answers(self):
        call_command('sync_survey_content', source=self.source, confirm=True, stdout=StringIO())

        q1, q2 = (Question.objects.get(pk=q.pk) for q in self.questions[1:3])
        self.assertEqual((q1.topic, q1.question_text, q1.section_title), ('Order Speed', 'Question 1 text?', SECTIONS[0][0]))
        self.assertEqual(list(q2.choices.order_by('id').values_list('choice_text', flat=True)), ['Friendly', 'Rude'])
        self.assertEqual(Question.objects.get(pk=self.questions[5].pk).section_title, SECTIONS[2][0])   # filled-in section
        self.assertIsNone(Question.objects.get(pk=self.questions[0].pk).section_title)                 # screening
        self.assertFalse(Choice.objects.filter(choice_text__contains='Q46').exists())
        answer = Answer.objects.get(pk=self.answer.pk)
        self.assertEqual(list(answer.selected_choices.values_list('choice_text', flat=True)), ['Under 3 minutes.'])

    def test_question_page_shows_the_section_name(self):
        call_command('sync_survey_content', source=self.source, confirm=True, stdout=StringIO())
        self.client.force_login(self.response.user)
        self.client.post(reverse('surveys:survey_question', args=[self.survey.id, 0]),
                         {f'question_{self.questions[0].id}': [str(self.questions[0].choices.get(choice_text='Real Brand').id)]})

        page = self.client.get(reverse('surveys:survey_question', args=[self.survey.id, 1]))
        self.assertContains(page, 'Part 1 of 4')
        self.assertContains(page, 'Customer Satisfaction Index (CSI)')
        self.assertContains(page, 'title="Part 2: Brand Reputation Ranking"')      # part strip tooltips
        self.assertNotContains(page, '⏱')
        self.assertRegex(page.content.decode(), r'class="question-topic">\s*<span class="question-number">Q1\.</span>\s*Order Speed')
        self.assertRegex(page.content.decode(), r'class="question-text">Question 1 text\?</span>')
