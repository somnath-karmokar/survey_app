"""Replace every survey with the 'New Enterprise Surveys' Word documents.

    python manage.py replace_surveys                       # dry run: what would be removed and imported
    python manage.py replace_surveys --confirm             # do it (irreversible - back up the database first)
    python manage.py replace_surveys --source new_surveys  # folder of "New Enterprise Surveys - <Country>" folders

In one transaction (all or nothing):
1. Full user reset via reset_survey_progress (survey responses and counts, draw
   entries, Monthly winning numbers and settlements, milestones, wallet
   transactions, withdrawal requests, wallet balances). Admin/staff accounts are skipped.
2. Delete every old survey category, survey, question, answer option and response.
3. Import each document as one category for its country, holding one survey:
   the screening question (multi-select, red options marked untruthful)
   followed by all the document's questions, in document order.
"""
import os
from collections import defaultdict

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from surveys.models import (
    Answer, Choice, Country, Question, Survey, SurveyCategory, SurveyResponse, UserSurveyProgress,
)
from surveys.survey_import import parse_document, survey_files

COUNTRY_FOLDERS = {'canada': 'CA', 'nigeria': 'NG', 'uk': 'GB', 'usa': 'US'}


class Command(BaseCommand):
    help = 'Replace all surveys with the New Enterprise Surveys documents (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='new_surveys', help='Folder of country folders of .docx files.')
        parser.add_argument('--confirm', action='store_true', help='Actually delete and import.')

    def handle(self, *args, **options):
        source = options['source']
        if not os.path.isdir(source):
            raise CommandError(f'No folder {source}.')

        plan = self.build_plan(source)
        countries = {c.code.upper() if isinstance(c.code, str) else str(c.code).upper(): c for c in Country.objects.all()}
        missing = sorted({code for code, _ in plan} - set(countries))
        if missing:
            raise CommandError(f'No Country with code {", ".join(missing)} in the database. Nothing was changed.')

        self.stdout.write('Will import:')
        by_country = defaultdict(list)
        for code, doc in plan:
            by_country[code].append(doc)
        for code, docs in sorted(by_country.items()):
            questions = sum(len(d['questions']) + 1 for d in docs)
            reds = sum(sum(o['red'] for o in d['screening']['options']) for d in docs)
            self.stdout.write(f'  {countries[code].name:28} {len(docs):3} categories/surveys, '
                              f'{questions:6} questions, {reds:3} untruthful screening options')
        self.stdout.write('Will delete (catalogue):')
        for label, count in (
            ('Survey categories', SurveyCategory.objects.count()),
            ('Surveys', Survey.objects.count()),
            ('Questions', Question.objects.count()),
            ('Answer options', Choice.objects.count()),
            ('Survey responses (all users)', SurveyResponse.objects.count()),
            ('  their answers', Answer.objects.count()),
            ('Survey completion counts', UserSurveyProgress.objects.count()),
        ):
            self.stdout.write(f'  {label:40} {count:>8}')
        self.stdout.write('User reset (draws, milestones, wallets) - from reset_survey_progress:')
        call_command('reset_survey_progress', stdout=self.stdout)

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('\nDry run only. Back up the database, then re-run with --confirm.'))
            return

        with transaction.atomic():
            call_command('reset_survey_progress', confirm=True, stdout=self.stdout)
            UserSurveyProgress.objects.all().delete()
            SurveyResponse.objects.all().delete()          # also deletes their answers
            Question.objects.all().delete()                # also deletes answer options
            Survey.objects.all().delete()
            SurveyCategory.objects.all().delete()
            totals = self.import_plan(plan, countries)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Imported {totals['categories']} categories/surveys, {totals['questions']} questions and "
            f"{totals['choices']} answer options ({totals['red']} untruthful)."
        ))

    def build_plan(self, source):
        """[(country code, parsed document)], one per category; on duplicate names keep the newest file."""
        chosen = {}
        for folder, path in survey_files(source):
            key = folder.rsplit('-', 1)[-1].strip().lower()
            code = COUNTRY_FOLDERS.get(key)
            if not code:
                raise CommandError(f'Unknown country folder "{folder}". Expected one of {sorted(COUNTRY_FOLDERS)}.')
            doc = parse_document(path)
            if doc['warnings']:
                raise CommandError(f'{path}: {"; ".join(doc["warnings"])}. Nothing was changed.')
            doc['path'] = path
            name_key = (code, doc['name'].lower())
            previous = chosen.get(name_key)
            if previous and os.path.getmtime(previous['path']) >= os.path.getmtime(path):
                self.stdout.write(f'  Duplicate "{doc["name"]}" ({code}): keeping {os.path.basename(previous["path"])}')
                continue
            if previous:
                self.stdout.write(f'  Duplicate "{doc["name"]}" ({code}): keeping {os.path.basename(path)} (newer)')
            chosen[name_key] = doc
        return sorted(((code, doc) for (code, _), doc in chosen.items()), key=lambda x: (x[0], x[1]['name'].lower()))

    def import_plan(self, plan, countries):
        totals = {'categories': 0, 'questions': 0, 'choices': 0, 'red': 0}
        order_in_country = defaultdict(int)
        through = Question.surveys.through
        for code, doc in plan:
            country = countries[code]
            order_in_country[code] += 1
            category = SurveyCategory.objects.create(name=doc['name'], country=country, order=order_in_country[code])
            survey = Survey.objects.create(
                name=doc['name'], category=category, level=1, is_active=True,
                description=f"{doc['name']} customer survey.",
            )

            entries = [doc['screening']] + doc['questions']
            questions = Question.objects.bulk_create([
                Question(
                    topic=(q.get('title') or None) and q['title'][:255],
                    question_text=q['text'],
                    question_type=q['type'],
                    is_required=True,
                    order=position,
                    not_listed_label=(q.get('not_listed_label') or '')[:120],
                    section_title=(q.get('section') or None) if position else None,
                )
                for position, q in enumerate(entries)
            ])
            through.objects.bulk_create([through(question_id=q.id, survey_id=survey.id) for q in questions])
            choices = [
                Choice(question=question, choice_text=option['text'][:500], is_disqualifying=option['red'])
                for question, entry in zip(questions, entries)
                for option in entry['options']
            ]
            Choice.objects.bulk_create(choices, batch_size=1000)

            totals['categories'] += 1
            totals['questions'] += len(questions)
            totals['choices'] += len(choices)
            totals['red'] += sum(c.is_disqualifying for c in choices)
        return totals
