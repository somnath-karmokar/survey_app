"""Reload chosen survey categories from their Word documents, leaving everything else alone.

    python manage.py reload_categories "Airlines" "Broadband and cables"            # dry run
    python manage.py reload_categories "Airlines" "Broadband and cables" --confirm  # apply
    ... --country GB --country US      # only these countries (default: every country with a document)

For each country that has a document for the category ("New Enterprise Surveys - <Country>"):
  - the category is kept (its image, description, order and link stay the same), or
    created when it was deleted;
  - its old survey, questions and answer options are removed and the survey is
    imported fresh from the document (Screening Gate, topics, sections, options).
A category whose survey already has user responses is NOT reloaded (reported), so
no user's answers, draws or wallet entries are ever lost. All in one transaction.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from surveys.models import Country, Question, Survey, SurveyCategory, SurveyResponse
from surveys.survey_import import parse_document, survey_files

from .replace_surveys import COUNTRY_FOLDERS, import_survey


def norm(name):
    return ' '.join(name.lower().split())


class Command(BaseCommand):
    help = 'Reload chosen survey categories from their documents (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('categories', nargs='+', help='Category names, as in the document titles.')
        parser.add_argument('--country', action='append', default=[], help='Country code(s), e.g. GB. Default: all.')
        parser.add_argument('--source', default='new_surveys')
        parser.add_argument('--confirm', action='store_true')

    def handle(self, *args, **options):
        wanted = {norm(c) for c in options['categories']}
        only = {c.upper() for c in options['country']}
        countries = {str(c.code).upper(): c for c in Country.objects.all()}

        plan, found = [], set()
        for folder, path in survey_files(options['source']):
            code = COUNTRY_FOLDERS.get(folder.rsplit('-', 1)[-1].strip().lower())
            if not code or (only and code not in only):
                continue
            doc = parse_document(path)
            if norm(doc['name']) not in wanted:
                continue
            if doc['warnings'] or doc['screening'] is None:
                raise CommandError(f'{path}: {"; ".join(doc["warnings"]) or "no Screening Gate"}. Nothing was changed.')
            if code not in countries:
                raise CommandError(f'No Country with code {code}. Nothing was changed.')
            found.add(norm(doc['name']))
            plan.append((countries[code], doc, path))
        missing = wanted - found
        if missing:
            raise CommandError(f'No document found for: {", ".join(sorted(missing))}. Nothing was changed.')

        actions, blocked = [], []
        for country, doc, path in sorted(plan, key=lambda p: (norm(p[1]['name']), p[0].name)):
            category = SurveyCategory.objects.filter(country=country, name__iexact=doc['name']).first()
            surveys = list(Survey.objects.filter(category=category)) if category else []
            responses = SurveyResponse.objects.filter(survey__in=surveys).count()
            label = f"{doc['name']} - {country.name}"
            if responses:
                blocked.append(f'{label}: {responses} user response(s) - left unchanged')
                continue
            questions = sum(s.questions.count() for s in surveys)
            what = (f'reload into existing category (id {category.id}); remove {len(surveys)} old survey(s) '
                    f'with {questions} question(s)' if category else 'create the category (it was deleted)')
            self.stdout.write(f'  {label}: {what}; import {len(doc["questions"]) + 1} questions')
            actions.append((country, doc, category, surveys))
        for line in blocked:
            self.stdout.write(self.style.WARNING(f'  Skipped {line}'))

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to apply.'))
            return

        created = []
        with transaction.atomic():
            for country, doc, category, surveys in actions:
                if surveys:
                    # Questions belong to one survey each; delete them (and their options) with the survey.
                    question_ids = set(Question.objects.filter(surveys__in=surveys).values_list('id', flat=True))
                    Question.objects.filter(id__in=question_ids).delete()
                    Survey.objects.filter(id__in=[s.id for s in surveys]).delete()
                if category is None:
                    last = SurveyCategory.objects.filter(country=country).aggregate(m=Max('order'))['m'] or 0
                    category = SurveyCategory.objects.create(name=doc['name'], country=country, order=last + 1)
                    created.append(category)
                counts = import_survey(category, doc)
                self.stdout.write(f"  {doc['name']} - {country.name}: survey {counts['survey'].id}, "
                                  f"{counts['questions']} questions, {counts['choices']} options "
                                  f"({counts['red']} untruthful)")
        self.stdout.write(self.style.SUCCESS(
            f'Done: {len(actions)} categories reloaded'
            + (f', {len(created)} recreated (ids {", ".join(str(c.id) for c in created)}) - '
               'run restore_category_images to give them their old image and description.' if created else '.')))
