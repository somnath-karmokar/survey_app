"""Give the new survey categories the images the old categories had.

    python manage.py restore_category_images --backup <surveys_surveycategory.csv>            # dry run
    python manage.py restore_category_images --backup <surveys_surveycategory.csv> --confirm  # apply

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
        parser.add_argument('--overwrite', action='store_true', help='Also replace images categories already have.')

    def handle(self, *args, **options):
        try:
            with open(options['backup'], encoding='utf-8', newline='') as f:
                old_rows = [r for r in csv.DictReader(f) if r.get('image')]
        except OSError as e:
            raise CommandError(f'Cannot read {options["backup"]}: {e}')

        by_country, anywhere = {}, {}
        for row in old_rows:
            key = normalise(row['name'])
            key = OLD_EQUIVALENTS.get(key, key)
            by_country.setdefault((row['country_id'], key), row['image'])
            anywhere.setdefault(key, row['image'])

        plan, unmatched = [], []
        for category in SurveyCategory.objects.select_related('country').order_by('country__name', 'name'):
            if category.image and not options['overwrite']:
                continue
            key = normalise(category.name)
            key = ALIASES.get(key, key)
            image = by_country.get((str(category.country_id), key))
            source = 'same country'
            if image is None:
                image, source = anywhere.get(key), 'other country'
            if image is None:
                unmatched.append(category)
                continue
            plan.append((category, image, source))

        for category, image, source in plan:
            self.stdout.write(f'  {str(category.country):28} {category.name[:45]:45} <- {image}'
                              + ('' if source == 'same country' else f'  ({source})'))
        for category in unmatched:
            self.stdout.write(self.style.WARNING(f'  {str(category.country):28} {category.name}: no old image found'))
        self.stdout.write(f'{len(plan)} categories get an image, {len(unmatched)} without a match.')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to apply.'))
            return
        with transaction.atomic():
            for category, image, _ in plan:
                SurveyCategory.objects.filter(pk=category.pk).update(image=image)
        self.stdout.write(self.style.SUCCESS(f'Updated {len(plan)} categories.'))
