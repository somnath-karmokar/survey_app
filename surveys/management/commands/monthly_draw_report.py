"""Read-only report explaining each country's Monthly draw status.

    python manage.py monthly_draw_report
    python manage.py monthly_draw_report --country GB
"""
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
            local_now, month_start, _next = month_bounds(config.tzinfo)
            totals_now = dict(
                UserSurveyProgress.objects.filter(user__profile__country=country)
                .values_list('user_id').annotate(t=Sum('completed_count'))
            )
            responses_all = dict(
                SurveyResponse.objects.filter(user__profile__country=country, completed_at__isnull=False)
                .values_list('user_id').annotate(c=Count('id'))
            )
            responses_before = dict(
                SurveyResponse.objects.filter(user__profile__country=country, completed_at__lt=month_start)
                .values_list('user_id').annotate(c=Count('id'))
            )
            qualifiers = view.get_monthly_milestone_qualifiers(country, required)

            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"{country.name} ({country.code}) [{config.time_zone}, local {local_now:%Y-%m-%d %H:%M}]: "
                f"{qualifiers} new-milestone user(s) this month"
                + (f" of {min_qualifiers} needed" if min_qualifiers else '')
                + f" | winners this month: {view.get_monthly_winner_count(country)}"
                + f" of {config.monthly_winner_cap or 'no cap'}"
            ))
            self.stdout.write(
                f"  {'user':30} {'total':>6} {'resp.all':>8} {'resp.<month':>11} {'attempts':>8}  counts?  why"
            )

            reached = sorted(
                ((uid, t or 0) for uid, t in totals_now.items() if (t or 0) >= required),
                key=lambda row: -row[1],
            )
            if not reached:
                self.stdout.write(f"  (nobody in {country.code} has {required}+ surveys)")
            for user_id, total in reached:
                before = responses_before.get(user_id, 0)
                crossed = total // required > before // required
                last = (
                    LuckyDrawEntry.objects.filter(user_id=user_id, draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY)
                    .order_by('-created_at').values_list('surveys_at_play', flat=True).first()
                ) or 0
                attempts = max(0, (total - last) // required)
                if crossed:
                    why = f"passed {total // required * required} this month"
                else:
                    why = f"already had {before} before {month_start:%b %d}"
                all_resp = responses_all.get(user_id, 0)
                if all_resp != total:
                    why += f" | NOTE: survey count {total} != {all_resp} responses"
                username = UserSurveyProgress.objects.filter(user_id=user_id).values_list(
                    'user__username', flat=True).first()
                self.stdout.write(
                    f"  {username[:30]:30} {total:>6} {all_resp:>8} {before:>11} {attempts:>8}  "
                    f"{'YES' if crossed else 'no':7}  {why}"
                )
