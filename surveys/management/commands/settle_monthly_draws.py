"""Settle ended Monthly draw days: when too few qualified for the draw to run,
pay every unused Monthly attempt the country's Monthly prize.

    python manage.py settle_monthly_draws                                  # everything due now
    python manage.py settle_monthly_draws --date 2026-10-08 --dry-run      # preview a missed day
    python manage.py settle_monthly_draws --date 2026-10-08 --date 2026-10-09

Safe to run as often as you like: each country's draw day is settled once.
--date settles specific ended draw days (e.g. test dates missed before they
were recorded automatically); --dry-run shows who would be paid without paying.
"""
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from surveys.lucky_draw import LuckyDrawView, MONTHLY_PAYOUT_FROM, draw_cycle, format_money
from surveys.models import CountryLuckyDrawConfig, MonthlyDrawSettlement


class Command(BaseCommand):
    help = 'Settle ended Monthly draw days and pay out where the draw could not run.'

    def add_arguments(self, parser):
        parser.add_argument('--date', action='append', default=[], help='YYYY-MM-DD draw day to settle (repeatable).')
        parser.add_argument('--dry-run', action='store_true', help='Show what would happen; pay nothing.')

    def handle(self, *args, **options):
        try:
            dates = sorted({date.fromisoformat(d) for d in options['date']})
        except ValueError:
            raise CommandError('--date must look like 2026-10-08')
        view = LuckyDrawView()
        required = max(1, settings.LUCKY_DRAW_CONFIG.get('MONTHLY_SURVEYS_REQUIRED', 100))
        min_qualifiers = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_MIN_QUALIFIERS', 5)
        configs = CountryLuckyDrawConfig.objects.filter(
            is_active=True, monthly_prize_amount__isnull=False,
        ).select_related('country')

        for config in configs:
            today = timezone.localtime(timezone.now(), config.tzinfo).date()
            due = dates or view.monthly_draw_days_to_settle(config)
            for draw_date in due:
                label = f'{config.country.name} {draw_date}'
                if draw_date >= today:
                    self.stdout.write(f'{label}: not over yet in {config.time_zone} - skipped')
                    continue
                if draw_date < MONTHLY_PAYOUT_FROM:
                    self.stdout.write(f'{label}: before payouts started ({MONTHLY_PAYOUT_FROM}) - skipped')
                    continue
                existing = MonthlyDrawSettlement.objects.filter(country=config.country, draw_date=draw_date).first()
                if existing:
                    self.stdout.write(f'{label}: already settled ({existing.paid_users} user(s) paid)')
                    continue

                cycle = draw_cycle(draw_date, config.tzinfo)
                earned = view.earned_attempts_by_user(config.country, required, cycle, until=cycle[1])
                qualifiers = sum(earned.values())
                if (not min_qualifiers) or qualifiers >= min_qualifiers:
                    outcome = f'{qualifiers} qualified attempt(s) - draw ran, nothing to pay'
                    payees = []
                else:
                    payees = [(user_id, n - view.monthly_attempts_used(user_id, cycle)) for user_id, n in earned.items()]
                    payees = [(user_id, n) for user_id, n in payees if n > 0]
                    outcome = f'{qualifiers} qualified attempt(s) of {min_qualifiers} - no draw'

                if options['dry_run']:
                    self.stdout.write(f'{label}: {outcome} [dry run]')
                    from django.contrib.auth import get_user_model
                    for user_id, n in payees:
                        email = get_user_model().objects.filter(pk=user_id).values_list('email', flat=True).first()
                        self.stdout.write(f'    would pay {email}: {n} x {config.get_monthly_prize_display()} = '
                                          f'{format_money(config.currency_symbol, config.monthly_prize_amount * n)}')
                    continue

                settlement = view.settle_monthly_draw(config, draw_date)
                self.stdout.write(f'{label}: {outcome}; {settlement.paid_users} user(s) paid')
        self.stdout.write(self.style.SUCCESS('Done.' if not options['dry_run'] else 'Dry run only - nothing paid.'))
