"""Give the new survey categories the images (or descriptions) the old categories had.

    python manage.py restore_category_images --backup <surveys_surveycategory.csv>            # dry run
    python manage.py restore_category_images --backup <surveys_surveycategory.csv> --confirm  # apply
    ... --descriptions                                       # the text under each category name instead

The CSV is the old surveys_surveycategory table (saved before replace_surveys).
Deleting a category does not delete its image file, so each new category is
simply pointed at the old file: same country first, then the same category in
another country. Only categories without an image are changed (use --overwrite
to replace existing ones).
"""
import csv
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from surveys.models import SurveyCategory

COUNTRY_PREFIX = re.compile(r'^\s*(nigeria|canada|u\.?\s*k\.?|u\.?\s*s\.?\s*a\.?)\s+', re.IGNORECASE)

# New category name (normalised) -> old category name (normalised), where they differ.
ALIASES = {
    'airlines': 'local airlines',
    'banking reatil': 'banking retail banks',
    'banking retail': 'banking retail banks',
    'cinema': 'cinemas',
    'food delivery takeaway': 'food delivery takeaway apps',
    'beauty cosmetics retailers': 'beauty cosmetics retailers',
    'streaming music services': 'worldwide streaming music services',
    'video streaming media services': 'video streaming media services',
    'insurance general car home': 'insurance general car home',
    'restaurants and family dining not fast food chains': 'restaurants and family dining not fast food chains',
    # No old category of the same kind: closest image.
    'online marketplace': 'discount stores',
    'markets comparison': 'buy now pay later services',
    'consumer credit bureaus': 'banking retail banks',
}
# Old names that mean the same as another old name.
OLD_EQUIVALENTS = {
    'beauty cosmetics retailer': 'beauty cosmetics retailers',
    'streaming media services': 'video streaming media services',
    'streaming music services': 'worldwide streaming music services',
    'buy now pay later services klarna clearpay': 'buy now pay later services',
    'restaurants family dining not fast food chains': 'restaurants and family dining not fast food chains',
}


# Categories with no old equivalent get their own description (their image is borrowed).
NEW_DESCRIPTIONS = {
    'markets comparison': (
        'Price comparison and market comparison sites help shoppers compare insurance, energy, broadband, '
        'credit cards and everyday products side by side, so they can find better deals and switch providers '
        'with confidence.'),
    'online marketplace': (
        'Online marketplaces bring thousands of independent sellers and brands together in one place, offering '
        'wide choice, competitive prices, customer reviews and convenient delivery and returns.'),
    'consumer credit bureaus': (
        'Consumer credit bureaus collect and score credit history, helping lenders make decisions and giving '
        'people access to their credit reports, scores and tools to monitor and improve their financial standing.'),
}


def normalise(name):
    name = COUNTRY_PREFIX.sub('', name or '')
    name = name.replace('&', ' ').replace('_', ' ')
    name = re.sub(r'[^a-z0-9]+', ' ', name.lower())
    return re.sub(r'\s+', ' ', name).strip()


class Command(BaseCommand):
    help = 'Point new survey categories at the old categories\' images (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--backup', required=True, help='CSV of the old surveys_surveycategory table.')
        parser.add_argument('--confirm', action='store_true')
        parser.add_argument('--overwrite', action='store_true', help='Also replace values categories already have.')
        parser.add_argument('--descriptions', action='store_true',
                            help='Restore the category descriptions (the text under the name) instead of images.')

    def handle(self, *args, **options):
        field = 'description' if options['descriptions'] else 'image'
        try:
            with open(options['backup'], encoding='utf-8', newline='') as f:
                old_rows = [r for r in csv.DictReader(f) if (r.get(field) or '').strip()]
        except OSError as e:
            raise CommandError(f'Cannot read {options["backup"]}: {e}')

        by_country, anywhere = {}, {}
        for row in old_rows:
            key = normalise(row['name'])
            key = OLD_EQUIVALENTS.get(key, key)
            by_country.setdefault((row['country_id'], key), row[field])
            anywhere.setdefault(key, row[field])

        plan, unmatched = [], []
        for category in SurveyCategory.objects.select_related('country').order_by('country__name', 'name'):
            if (getattr(category, field) or '') and not options['overwrite']:
                continue
            key = normalise(category.name)
            if field == 'description' and key in NEW_DESCRIPTIONS:
                # No old category of this kind: a borrowed text would describe another business.
                plan.append((category, NEW_DESCRIPTIONS[key], 'new text'))
                continue
            key = ALIASES.get(key, key)
            value = by_country.get((str(category.country_id), key))
            source = 'same country'
            if value is None:
                value, source = anywhere.get(key), 'other country'
            if value is None:
                unmatched.append(category)
                continue
            plan.append((category, value, source))

        for category, value, source in plan:
            shown = value if field == 'image' else ' '.join(value.split())[:60] + '...'
            self.stdout.write(f'  {str(category.country):28} {category.name[:45]:45} <- {shown}'
                              + ('' if source == 'same country' else f'  ({source})'))
        for category in unmatched:
            self.stdout.write(self.style.WARNING(f'  {str(category.country):28} {category.name}: no old {field} found'))
        self.stdout.write(f'{len(plan)} categories get a{"n" if field == "image" else ""} {field}, '
                          f'{len(unmatched)} without a match.')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to apply.'))
            return
        with transaction.atomic():
            for category, value, _ in plan:
                SurveyCategory.objects.filter(pk=category.pk).update(**{field: value})
        self.stdout.write(self.style.SUCCESS(f'Updated {len(plan)} categories.'))
