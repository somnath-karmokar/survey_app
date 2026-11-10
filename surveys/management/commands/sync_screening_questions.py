"""Bring the live screening questions in line with the Word documents, without
touching any user data.

    python manage.py sync_screening_questions              # dry run: list what would change
    python manage.py sync_screening_questions --confirm    # apply

For every imported survey (matched by country + category name) it re-reads the
document's screening question and updates, in place:
  - which answer options are untruthful (red, including dark red), and
  - the type-your-own box (the green line), e.g. "fast food chain".
Questions, options, responses, draws and wallets are otherwise left alone.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from surveys.models import Choice, Country, Question, Survey
from surveys.survey_import import parse_document, survey_files

from .replace_surveys import COUNTRY_FOLDERS


class Command(BaseCommand):
    help = 'Update screening questions (untruthful options, "not listed" box) from the documents.'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='new_surveys')
        parser.add_argument('--confirm', action='store_true')

    def handle(self, *args, **options):
        countries = {str(c.code).upper(): c for c in Country.objects.all()}
        documents = {}
        for folder, path in survey_files(options['source']):
            code = COUNTRY_FOLDERS.get(folder.rsplit('-', 1)[-1].strip().lower())
            if not code:
                raise CommandError(f'Unknown country folder "{folder}".')
            doc = parse_document(path)
            documents[(code, doc['name'].lower())] = doc     # same name: either file has the same screening

        changes, missing = [], []
        for survey in Survey.objects.select_related('category__country'):
            code = str(survey.category.country.code).upper() if survey.category.country else ''
            doc = documents.get((code, survey.category.name.lower()))
            if doc is None or doc['screening'] is None:
                missing.append(f'{code} {survey.category.name}')
                continue
            screening = survey.questions.filter(order=0).first()
            if screening is None:
                missing.append(f'{code} {survey.category.name} (no question at position 0)')
                continue
            red_texts = {o['text'][:500] for o in doc['screening']['options'] if o['red']}
            choices = list(screening.choices.all())
            flips = [c for c in choices if c.is_disqualifying != (c.choice_text in red_texts)]
            label = (doc['screening'].get('not_listed_label') or '')[:120]
            if flips or screening.not_listed_label != label:
                changes.append((survey, screening, flips, label, red_texts))

        for survey, screening, flips, label, _ in changes:
            code = str(survey.category.country.code).upper()
            self.stdout.write(f'{code} {survey.category.name}:')
            for c in flips:
                self.stdout.write(f'    {"untruthful" if not c.is_disqualifying else "truthful  "} <- "{c.choice_text}"')
            if screening.not_listed_label != label:
                self.stdout.write(f'    type-your-own box: "{screening.not_listed_label}" -> "{label}"')
        for name in missing:
            self.stdout.write(self.style.WARNING(f'No document for {name} - left unchanged.'))
        self.stdout.write(f'{len(changes)} screening question(s) to update.')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to apply.'))
            return
        with transaction.atomic():
            for survey, screening, flips, label, red_texts in changes:
                for c in flips:
                    Choice.objects.filter(pk=c.pk).update(is_disqualifying=c.choice_text in red_texts)
                Question.objects.filter(pk=screening.pk).update(not_listed_label=label)
        self.stdout.write(self.style.SUCCESS(f'Updated {len(changes)} screening question(s).'))
