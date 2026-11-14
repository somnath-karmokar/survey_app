"""Re-read the survey documents and correct the imported surveys in place.

    python manage.py sync_survey_content              # dry run: what would change
    python manage.py sync_survey_content --confirm    # apply

For every survey (matched by country + category name) it re-parses the document
with the current importer and, keeping every question's id (so users' answers,
progress, draws and wallets are untouched):
  - sets each question's section ("Customer Satisfaction Index (CSI)", ...),
  - stores each question's topic (the "Q01." line) separately from the question text,
  - removes emojis from question and answer-option text,
  - deletes answer options that were really section headings or their notes
    (e.g. "Index 2 — Brand Reputation Ranking"), which older imports added by mistake.
A survey whose question count differs from its document, or a question whose
options don't line up with the document, is reported and left unchanged.
Surveys removed in the admin are not recreated.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from surveys.models import Answer, Choice, Question, Survey
from surveys.survey_import import parse_document, strip_emojis, survey_files

from .replace_surveys import COUNTRY_FOLDERS


def same(a, b):
    return re.sub(r'\s+', ' ', strip_emojis(a)).strip() == re.sub(r'\s+', ' ', b).strip()


class Command(BaseCommand):
    help = 'Fix sections, emojis and heading-options of the imported surveys in place (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='new_surveys')
        parser.add_argument('--confirm', action='store_true')

    def handle(self, *args, **options):
        documents = {}
        for folder, path in survey_files(options['source']):
            code = COUNTRY_FOLDERS.get(folder.rsplit('-', 1)[-1].strip().lower())
            if not code:
                raise CommandError(f'Unknown country folder "{folder}".')
            doc = parse_document(path)
            documents[(code, doc['name'].lower())] = doc

        question_updates, choice_updates, choice_deletes, skipped = [], [], [], []
        surveys_changed = 0
        for survey in Survey.objects.select_related('category__country').order_by('category__country__name', 'name'):
            code = str(survey.category.country.code).upper() if survey.category.country else ''
            label = f'{code} {survey.category.name}'
            doc = documents.get((code, survey.category.name.lower()))
            if doc is None or doc['screening'] is None:
                skipped.append(f'{label}: no matching document')
                continue
            questions = list(survey.questions.order_by('order', 'id').prefetch_related('choices'))
            entries = [doc['screening']] + doc['questions']
            if len(questions) != len(entries):
                skipped.append(f'{label}: {len(questions)} questions here, {len(entries)} in the document')
                continue
            changed = False
            for position, (question, entry) in enumerate(zip(questions, entries)):
                text = entry['text']
                topic = (entry.get('title') or None) and entry['title'][:255]
                section = (entry.get('section') or None) if position else None     # screening: no section
                fields = {}
                if question.question_text != text:
                    fields['question_text'] = text
                if (question.topic or None) != topic:
                    fields['topic'] = topic
                if (question.section_title or None) != section:
                    fields['section_title'] = section
                db_choices = sorted(question.choices.all(), key=lambda c: c.id)
                new_options = entry['options']
                if len(db_choices) < len(new_options) or not all(
                        same(c.choice_text, o['text']) for c, o in zip(db_choices, new_options)):
                    skipped.append(f'{label} question {position}: options differ from the document - left as is')
                    continue
                if fields:
                    question_updates.append((question.pk, fields))
                    changed = True
                for choice, option in zip(db_choices, new_options):
                    if choice.choice_text != option['text']:
                        choice_updates.append((choice.pk, option['text'][:500]))
                        changed = True
                for extra in db_choices[len(new_options):]:
                    choice_deletes.append((label, position, extra))
                    changed = True
            surveys_changed += changed

        picked = Answer.objects.filter(selected_choices__in=[c.pk for _, _, c in choice_deletes]).distinct().count()
        self.stdout.write(f'Surveys to correct: {surveys_changed}')
        self.stdout.write(f'Questions to update (topic, text and/or section): {len(question_updates)}')
        self.stdout.write(f'Answer options to clean (emojis removed): {len(choice_updates)}')
        self.stdout.write(f'Answer options to delete (they were headings/notes): {len(choice_deletes)}'
                          f' - picked in {picked} user answer(s)')
        for label, position, choice in choice_deletes[:15]:
            self.stdout.write(f'    {label} q{position}: "{choice.choice_text[:70]}"')
        if len(choice_deletes) > 15:
            self.stdout.write(f'    ... and {len(choice_deletes) - 15} more')
        for line in skipped:
            self.stdout.write(self.style.WARNING(f'  Skipped: {line}'))

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to apply.'))
            return
        # Small batches, each committed on its own: fast over a remote database, and
        # safe to re-run (already-corrected rows are no longer reported as changes).
        batch = 500
        by_fields = {}
        for pk, fields in question_updates:
            by_fields.setdefault(tuple(sorted(fields)), []).append(Question(pk=pk, **fields))
        for names, objs in by_fields.items():
            for start in range(0, len(objs), batch):
                with transaction.atomic():
                    Question.objects.bulk_update(objs[start:start + batch], list(names))
        self.stdout.write(f'  questions saved: {len(question_updates)}')
        self.stdout.flush()
        choices = [Choice(pk=pk, choice_text=text) for pk, text in choice_updates]
        for start in range(0, len(choices), batch):
            with transaction.atomic():
                Choice.objects.bulk_update(choices[start:start + batch], ['choice_text'])
        self.stdout.write(f'  options saved: {len(choices)}')
        with transaction.atomic():
            Choice.objects.filter(pk__in=[c.pk for _, _, c in choice_deletes]).delete()
        self.stdout.write(self.style.SUCCESS(
            f'Done: {len(question_updates)} questions updated, {len(choice_updates)} options cleaned, '
            f'{len(choice_deletes)} heading options removed.'))
