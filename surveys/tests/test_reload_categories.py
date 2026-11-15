"""reload_categories: reload chosen categories from their documents, nothing else."""
import os
import shutil
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from surveys.models import Choice, Country, Question, Survey, SurveyCategory, SurveyResponse
from surveys.tests.test_survey_sections import write_doc


class ReloadCategoriesTests(TestCase):
    def setUp(self):
        self.source = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.source)
        for folder in ('New Enterprise Surveys - UK', 'New Enterprise Surveys - Nigeria'):
            os.makedirs(os.path.join(self.source, folder))
            write_doc(os.path.join(self.source, folder, 'Retail - Ready.docx'))
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.ng = Country.objects.create(name='Nigeria', code='NG')
        # UK: category kept, survey removed in the admin. Nigeria: category deleted.
        self.uk_retail = SurveyCategory.objects.create(name='Retail', country=self.uk, order=4,
                                                       description='Shops and stores.')
        self.other = SurveyCategory.objects.create(name='Cinema', country=self.uk, order=9)
        other_survey = Survey.objects.create(name='Cinema', category=self.other)
        Question.objects.create(question_text='Untouched?', question_type='text').surveys.add(other_survey)

    def run_command(self, *names, **kwargs):
        out = StringIO()
        call_command('reload_categories', *names, source=self.source, stdout=out, **kwargs)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        out = self.run_command('Retail')
        self.assertIn('Retail - United Kingdom: reload into existing category', out)
        self.assertIn('Retail - Nigeria: create the category (it was deleted)', out)
        self.assertFalse(Survey.objects.filter(category__name='Retail').exists())

    def test_reloads_into_the_kept_category_and_recreates_the_deleted_one(self):
        self.run_command('retail', confirm=True)

        kept = SurveyCategory.objects.get(pk=self.uk_retail.pk)
        self.assertEqual((kept.description, kept.order), ('Shops and stores.', 4))      # image/description/order kept
        survey = Survey.objects.get(category=kept)
        questions = list(survey.questions.order_by('order'))
        self.assertEqual(len(questions), 9)                                              # screening + 8
        self.assertTrue(questions[0].choices.filter(is_disqualifying=True).exists())
        self.assertEqual((questions[1].topic, questions[1].section_title), ('Order Speed', 'Customer Satisfaction Index (CSI)'))
        ng = SurveyCategory.objects.get(country=self.ng, name='Retail')
        self.assertEqual(Survey.objects.get(category=ng).questions.count(), 9)
        self.assertEqual(Question.objects.filter(surveys__category=self.other).count(), 1)  # other categories untouched

    def test_reloading_again_replaces_the_survey(self):
        self.run_command('Retail', confirm=True)
        self.run_command('Retail', confirm=True)
        self.assertEqual(Survey.objects.filter(category=self.uk_retail).count(), 1)
        self.assertEqual(Question.objects.filter(surveys__category=self.uk_retail).count(), 9)
        self.assertFalse(Question.objects.filter(surveys__isnull=True).exists())         # no orphans left
        self.assertFalse(Choice.objects.filter(question__surveys__isnull=True).exists())

    def test_a_category_with_user_responses_is_left_alone(self):
        survey = Survey.objects.create(name='Retail', category=self.uk_retail)
        user = get_user_model().objects.create_user('u@example.com', 'u@example.com', 'pw')
        SurveyResponse.objects.create(user=user, survey=survey)
        out = self.run_command('Retail', confirm=True)
        self.assertIn('Skipped Retail - United Kingdom: 1 user response(s)', out)
        self.assertEqual(list(Survey.objects.filter(category=self.uk_retail)), [survey])
        self.assertTrue(SurveyCategory.objects.filter(country=self.ng, name='Retail').exists())   # NG still done

    def test_only_given_countries(self):
        self.run_command('Retail', country=['NG'], confirm=True)
        self.assertFalse(Survey.objects.filter(category=self.uk_retail).exists())
        self.assertTrue(Survey.objects.filter(category__country=self.ng).exists())

    def test_unknown_category_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command('Pizza Places', confirm=True)
