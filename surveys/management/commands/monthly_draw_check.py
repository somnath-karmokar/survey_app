"""Explain, for one user, exactly why the Monthly draw is open or closed right now (read-only).

    python manage.py monthly_draw_check --email someone@example.com
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from surveys.lucky_draw import LuckyDrawView


class Command(BaseCommand):
    help = "Show why the Monthly draw is open or closed for one user right now (changes nothing)."

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(email__iexact=options['email']).select_related('profile__country').first()
        if not user:
            raise CommandError(f"No user with email {options['email']}.")

        view = LuckyDrawView()
        config = view.get_monthly_draw_config(user)
        country = getattr(user.profile, 'country', None)
        test_date = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_DRAW_TEST_DATE')
        now_utc = timezone.now()

        self.stdout.write(f'User:        {user.email}')
        self.stdout.write(f'Country:     {country or "none on profile"}')
        if not config:
            self.stdout.write(self.style.ERROR(
                'Monthly draw config: none, inactive, or no Monthly prize set for this country -> no Monthly draw.'
            ))
            return
        local_now = timezone.localtime(now_utc, config.tzinfo)
        self.stdout.write(f'Time zone:   {config.time_zone}'
                          + ('   <-- check: UTC is the default, set the real one in Country Lucky Draw Configs'
                             if config.time_zone == 'UTC' else ''))
        self.stdout.write(f'Now:         {now_utc:%Y-%m-%d %H:%M} UTC = {local_now:%Y-%m-%d %H:%M} local')
        self.stdout.write(f'Test date:   {test_date or "none"} (as deployed)')

        draw_days = [local_now.date().replace(day=1)]
        if test_date:
            draw_days.append(datetime.fromisoformat(test_date).date())
        for day in sorted(set(draw_days)):
            opens = datetime.combine(day, time.min, tzinfo=config.tzinfo)
            closes = datetime.combine(day + timedelta(days=1), time.min, tzinfo=config.tzinfo) - timedelta(minutes=1)
            self.stdout.write(f'Draw day {day}: open {opens:%d %b %H:%M} - {closes:%d %b %H:%M} local '
                              f'({opens.astimezone(timezone.utc):%d %b %H:%M} - '
                              f'{closes.astimezone(timezone.utc):%d %b %H:%M} UTC)')

        e = view.get_eligibility_context(user)
        rows = [
            ('Window open now', e['monthly_window_open']),
            (f"Qualifiers this month ({e['monthly_milestone_qualifiers']} of {e['monthly_min_qualifiers']} needed)",
             e['monthly_quorum_met']),
            (f"Prizes left ({e['monthly_winners_this_month']} of {e['monthly_winner_cap']} won)", e['monthly_open']),
            (f"User has an attempt ({e['monthly_plays_available']})", e['monthly_plays_available'] > 0),
        ]
        for label, ok in rows:
            self.stdout.write(f"  {'OK ' if ok else 'NO '} {label}")
        if e['monthly_eligible']:
            self.stdout.write(self.style.SUCCESS('Result: the user can play the Monthly draw now.'))
        else:
            self.stdout.write(self.style.WARNING(f'Result: cannot play. Page says: {view.monthly_play_error(user)}'))
