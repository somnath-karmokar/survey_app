"""List every country's lucky draw time zone and flag any that look wrong.

    python manage.py check_draw_time_zones            # read-only report
    python manage.py check_draw_time_zones --fix      # dry run of fixes for flagged countries
    python manage.py check_draw_time_zones --fix --confirm

A country is flagged when its time zone isn't a valid IANA name, or when it's
still the UTC default while a known time zone exists for its code. --fix only
sets the known time zone on flagged rows; it changes nothing else.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.management.base import BaseCommand
from django.utils import timezone

from surveys.models import CountryLuckyDrawConfig

KNOWN_TIME_ZONES = {
    'GB': 'Europe/London',
    'NG': 'Africa/Lagos',
    'US': 'America/New_York',
    'CA': 'America/Toronto',
    'IN': 'Asia/Kolkata',
    'AU': 'Australia/Sydney',
}


class Command(BaseCommand):
    help = "Check each country's lucky draw time zone (read-only unless --fix --confirm)."

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Set the known time zone on flagged countries.')
        parser.add_argument('--confirm', action='store_true', help='With --fix: actually save.')

    def handle(self, *args, **options):
        now = timezone.now()
        self.stdout.write(f'Now: {now:%Y-%m-%d %H:%M} UTC\n')
        self.stdout.write(f"{'Country':24} {'Code':5} {'Monthly':8} {'Time zone':20} {'Local now':17} "
                          f"{'Draw day 00:00 = UTC':21} Status")
        to_fix = []
        for config in CountryLuckyDrawConfig.objects.select_related('country').order_by('country__name'):
            code = str(config.country.code or '').upper()
            known = KNOWN_TIME_ZONES.get(code)
            monthly = 'yes' if (config.is_active and config.monthly_prize_amount is not None) else 'no'
            try:
                tz = ZoneInfo(config.time_zone)
                valid = True
            except (ZoneInfoNotFoundError, ValueError):
                tz, valid = None, False

            if not valid:
                status = f'INVALID time zone' + (f' -> should be {known}' if known else '')
                if known:
                    to_fix.append((config, known))
            elif known and config.time_zone != known:
                status = f'CHECK: expected {known}'
                if config.time_zone == 'UTC':
                    to_fix.append((config, known))
            elif config.time_zone == 'UTC' and monthly == 'yes':
                status = 'CHECK: still the UTC default'
            else:
                status = 'ok'

            if tz:
                local_now = timezone.localtime(now, tz)
                midnight = datetime.combine(local_now.date(), time.min, tzinfo=tz)
                offset = midnight.utcoffset() or timedelta(0)
                hours = offset.total_seconds() / 3600
                midnight_text = f'{midnight.astimezone(timezone.utc):%H:%M} UTC (UTC{hours:+g})'
                local_text = f'{local_now:%Y-%m-%d %H:%M}'
            else:
                midnight_text, local_text = '-', '-'
            self.stdout.write(f'{config.country.name[:24]:24} {code:5} {monthly:8} {config.time_zone[:20]:20} '
                              f'{local_text:17} {midnight_text:21} {status}')

        if not options['fix']:
            if to_fix:
                self.stdout.write(self.style.WARNING(f'\n{len(to_fix)} country(ies) can be fixed: run with --fix.'))
            else:
                self.stdout.write(self.style.SUCCESS('\nNo fixes needed.'))
            return

        for config, known in to_fix:
            self.stdout.write(f'Will set {config.country.name}: {config.time_zone} -> {known}')
        if not to_fix:
            self.stdout.write(self.style.SUCCESS('Nothing to fix.'))
            return
        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --fix --confirm to save.'))
            return
        for config, known in to_fix:
            CountryLuckyDrawConfig.objects.filter(pk=config.pk).update(time_zone=known)
        self.stdout.write(self.style.SUCCESS(f'Done. {len(to_fix)} time zone(s) updated.'))
