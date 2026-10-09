"""Read-only report explaining each country's Monthly draw status.

    python manage.py monthly_draw_report
    python manage.py monthly_draw_report --country GB
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from django.utils import timezone

from surveys.lucky_draw import LuckyDrawView, month_bounds
from surveys.models import CountryLuckyDrawConfig, LuckyDrawEntry, SurveyResponse, UserSurveyProgress


class Command(BaseCommand):
    help = "Show, per Monthly-draw country, who counts toward this month's minimum-qualifiers rule and why."

    def add_arguments(self, parser):
        parser.add_argument('--country', help='Country code, e.g. GB. Default: every Monthly-draw country.')

    def handle(self, *args, **options):
        cfg = settings.LUCKY_DRAW_CONFIG
        required = max(1, cfg.get('MONTHLY_SURVEYS_REQUIRED', 100))
        min_qualifiers = cfg.get('MONTHLY_MIN_QUALIFIERS', 5)
        view = LuckyDrawView()

        self.stdout.write(
            f"Now: {timezone.now():%Y-%m-%d %H:%M} UTC | milestone every {required} surveys | "
            f"minimum qualifiers: {min_qualifiers or 'off'} | test date: {cfg.get('MONTHLY_DRAW_TEST_DATE') or 'none'}"
        )

        configs = CountryLuckyDrawConfig.objects.filter(
            is_active=True, monthly_prize_amount__isnull=False,
        ).select_related('country')
        if options['country']:
            configs = configs.filter(country__code__iexact=options['country'])

        for config in configs:
            country = config.country
            local_now = timezone.localtime(timezone.now(), config.tzinfo)
            draw_day, cycle = view.get_monthly_cycle(config)
            totals_now = dict(
                UserSurveyProgress.objects.filter(user__profile__country=country)
                .values_list('user_id').annotate(t=Sum('completed_count'))
            )
            responses_all = dict(
                SurveyResponse.objects.filter(user__profile__country=country, completed_at__isnull=False)
                .values_list('user_id').annotate(c=Count('id'))
            )
            responses_before = dict(
                SurveyResponse.objects.filter(user__profile__country=country, completed_at__lt=cycle[0])
                .values_list('user_id').annotate(c=Count('id'))
            )
            earned_by_user = view.earned_attempts_by_user(country, required, cycle)
            qualifiers = sum(earned_by_user.values())
            cycle_end_day = (cycle[1] - timedelta(days=1)).date()

            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"{country.name} ({country.code}) [{config.time_zone}, local {local_now:%Y-%m-%d %H:%M}] "
                f"draw day {draw_day} (surveys {cycle[0]:%d %b} - {cycle_end_day:%d %b}): "
                f"{qualifiers} qualified attempt(s)"
                + (f" of {min_qualifiers} needed" if min_qualifiers else '')
                + f" | winners this month: {view.get_monthly_winner_count(country)}"
                + f" of {config.monthly_winner_cap or 'no cap'}"
            ))
            self.stdout.write(
                f"  {'user':30} {'total':>6} {'resp.all':>8} {'before':>7} {'earned':>6} {'unused':>6}  note"
            )

            listed = sorted(earned_by_user, key=lambda uid: -totals_now.get(uid, 0))
            if not listed:
                self.stdout.write(f"  (nobody in {country.code} has passed a {required}-survey milestone this cycle)")
            for user_id in listed:
                total = totals_now.get(user_id, 0) or 0
                before = responses_before.get(user_id, 0)
                earned = earned_by_user[user_id]
                unused = max(0, earned - view.monthly_attempts_used(user_id, cycle))
                all_resp = responses_all.get(user_id, 0)
                note = f"NOTE: survey count {total} != {all_resp} responses" if all_resp != total else ''
                username = UserSurveyProgress.objects.filter(user_id=user_id).values_list(
                    'user__username', flat=True).first()
                self.stdout.write(
                    f"  {username[:30]:30} {total:>6} {all_resp:>8} {before:>7} {earned:>6} {unused:>6}  {note}"
                )
