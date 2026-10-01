"""Settle ended Monthly draw days: when too few people qualified for the draw
to run, pay everyone who held a Monthly attempt the country's Monthly prize.

Safe to run as often as you like (each country's draw day is settled once).
Schedule it daily, e.g. as a Render Cron Job:

    python manage.py settle_monthly_draws
"""
from django.core.management.base import BaseCommand

from surveys.lucky_draw import LuckyDrawView
from surveys.models import CountryLuckyDrawConfig


class Command(BaseCommand):
    help = 'Settle ended Monthly draw days and pay out where the draw could not run.'

    def handle(self, *args, **options):
        view = LuckyDrawView()
        configs = CountryLuckyDrawConfig.objects.filter(
            is_active=True, monthly_prize_amount__isnull=False,
        ).select_related('country')
        for config in configs:
            for draw_date in view.monthly_draw_days_to_settle(config):
                settlement = view.settle_monthly_draw(config, draw_date)
                outcome = (
                    'draw ran, nothing to pay' if settlement.quorum_met
                    else f'draw did not run ({settlement.qualifiers} qualified), '
                         f'{settlement.paid_users} user(s) paid {config.get_monthly_prize_display()}'
                )
                self.stdout.write(f'{config.country.name} {draw_date}: {outcome}')
        self.stdout.write(self.style.SUCCESS('Done.'))
