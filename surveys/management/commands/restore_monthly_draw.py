"""Put back Monthly draw wins deleted by reset_monthly_draw, using the lines it printed.

    python manage.py restore_monthly_draw \\
        --winning-numbers 1,2,3,5 \\
        --entry "2026-10-06 07:04,sarahhalpin4@gmail.com,3" \\
        --entry "2026-10-06 07:01,pilkingtoncraig73@gmail.com,2" \\
        --entry "2026-10-06 06:57,agrusltd@gmail.com,5" \\
        --entry "2026-10-06 06:51,socials.sudraw@gmail.com,1"          # dry run; add --confirm to write

Times are UTC, as reset_monthly_draw printed them. For each entry it re-creates the
Monthly win (same user, number, time and prize, using up one Monthly attempt as the
original did) and re-links the wallet credit that reset_monthly_draw kept. It also
re-creates the month's winning numbers, and records the month's ended draw days as
settled without paying anyone, so the automatic check doesn't settle them again.
The country and month come from the users and times. Nothing is written if any
entry already exists, a user isn't found, or the users are in different countries.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from surveys.lucky_draw import LuckyDrawView, draw_cycle
from surveys.models import (
    CountryLuckyDrawConfig, LuckyDrawEntry, MonthlyDrawNumbers, MonthlyDrawSettlement, PollResponse,
    WalletTransaction,
)


class Command(BaseCommand):
    help = 'Re-create Monthly draw wins removed by reset_monthly_draw (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--entry', action='append', default=[],
                            help='"YYYY-MM-DD HH:MM,email,number" (UTC), one per deleted win. Required.')
        parser.add_argument('--winning-numbers', required=True, help='e.g. 1,2,3,5')
        parser.add_argument('--confirm', action='store_true', help='Actually write.')

    def handle(self, *args, **options):
        User = get_user_model()
        if not options['entry']:
            raise CommandError('Give at least one --entry "YYYY-MM-DD HH:MM,email,number".')
        try:
            winning_numbers = sorted(int(n) for n in options['winning_numbers'].split(','))
        except ValueError:
            raise CommandError('--winning-numbers must look like 1,2,3,5')

        entries = []
        for raw in options['entry']:
            try:
                when_text, email, number_text = (part.strip() for part in raw.split(','))
                when = datetime.strptime(when_text, '%Y-%m-%d %H:%M').replace(tzinfo=dt_timezone.utc)
                number = int(number_text)
            except ValueError:
                raise CommandError(f'Bad --entry "{raw}". Use "YYYY-MM-DD HH:MM,email,number".')
            user = User.objects.filter(email__iexact=email).select_related('profile__country').first()
            if not user:
                raise CommandError(f'No user with email {email}. Nothing was written.')
            if number not in winning_numbers:
                raise CommandError(f'{email}: number {number} is not in the winning numbers. Nothing was written.')
            entries.append((when, user, number))

        countries = {user.profile.country_id for _when, user, _number in entries}
        if len(countries) != 1 or None in countries:
            raise CommandError('All users must be in the same country. Nothing was written.')
        config = CountryLuckyDrawConfig.objects.filter(country_id=countries.pop()).select_related('country').first()
        if not config or config.monthly_prize_amount is None:
            raise CommandError('That country has no Monthly draw configured. Nothing was written.')

        local_times = [when.astimezone(config.tzinfo) for when, _user, _number in entries]
        year, month = local_times[0].year, local_times[0].month
        if any((t.year, t.month) != (year, month) for t in local_times):
            raise CommandError('All entries must be in the same month. Nothing was written.')

        view = LuckyDrawView()
        required = max(1, settings.LUCKY_DRAW_CONFIG.get('MONTHLY_SURVEYS_REQUIRED', 100))
        prize = config.get_monthly_prize_display()

        self.stdout.write(f'{config.country.name}, {date(year, month, 1):%B %Y}; winning numbers {winning_numbers}:')
        plans = []
        for when, user, number in sorted(entries, key=lambda e: e[0]):
            near = LuckyDrawEntry.objects.filter(
                user=user, draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY, guessed_number=number,
                created_at__gte=when - timedelta(minutes=1), created_at__lt=when + timedelta(minutes=2),
            )
            if near.exists():
                raise CommandError(f'{user.email} number {number} at {when:%Y-%m-%d %H:%M} still exists - '
                                   'it was not deleted (dry run?). Nothing was written.')
            credit = WalletTransaction.objects.filter(
                profile__user=user, lucky_draw_entry__isnull=True,
                transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
                created_at__gte=when - timedelta(minutes=1), created_at__lt=when + timedelta(minutes=5),
            ).order_by('created_at').first()
            previous = LuckyDrawEntry.objects.filter(
                user=user, draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY, created_at__lt=when,
            ).order_by('-created_at', '-id').first()
            snapshot = ((previous.surveys_at_play or 0) if previous else 0) + required
            plans.append((when, user, number, credit, snapshot))
            self.stdout.write(
                f'  {when:%Y-%m-%d %H:%M} UTC  {user.email:40} number {number}  WIN {prize}  '
                f'wallet credit: {"found, will re-link" if credit else "not found (left as is)"}'
            )

        existing_numbers = MonthlyDrawNumbers.objects.filter(country=config.country, year=year, month=month).first()
        self.stdout.write(f'  Winning numbers row: '
                          f'{"exists " + str(existing_numbers.winning_numbers) + " - will be set to " + str(winning_numbers) if existing_numbers else "will be created"}')

        tz = config.tzinfo
        now_local = timezone.localtime(timezone.now(), tz)
        draw_days = {date(year, month, 1)}
        test_date = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_DRAW_TEST_DATE')
        if test_date:
            try:
                parsed = date.fromisoformat(test_date)
                if (parsed.year, parsed.month) == (year, month):
                    draw_days.add(parsed)
            except ValueError:
                pass
        for t in local_times:
            draw_days.add(t.date())
        draw_days = sorted(d for d in draw_days if d < now_local.date()
                           and not MonthlyDrawSettlement.objects.filter(country=config.country, draw_date=d).exists())
        self.stdout.write(f'  Draw days to mark settled (nobody paid): '
                          f'{", ".join(str(d) for d in draw_days) or "none"}')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to write.'))
            return

        with transaction.atomic():
            for when, user, number, credit, snapshot in plans:
                entry = LuckyDrawEntry.objects.create(
                    user=user, draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
                    guessed_number=number, winning_number=number, is_winner=True, prize=prize,
                    surveys_at_play=snapshot, polls_at_play=PollResponse.objects.filter(user=user).count(),
                )
                LuckyDrawEntry.objects.filter(pk=entry.pk).update(created_at=when)
                if credit:
                    WalletTransaction.objects.filter(pk=credit.pk).update(lucky_draw_entry=entry)
            MonthlyDrawNumbers.objects.update_or_create(
                country=config.country, year=year, month=month, defaults={'winning_numbers': winning_numbers},
            )
            for draw_day in draw_days:
                day_end = datetime.combine(draw_day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
                qualifiers = view.get_monthly_qualified_attempts(
                    config.country, required, draw_cycle(draw_day, tz), until=day_end,
                )
                min_qualifiers = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_MIN_QUALIFIERS', 5)
                MonthlyDrawSettlement.objects.create(
                    country=config.country, draw_date=draw_day, qualifiers=qualifiers,
                    quorum_met=(not min_qualifiers) or qualifiers >= min_qualifiers, paid_users=0,
                )

        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(plans)} Monthly win(s) and the winning numbers restored for '
            f'{config.country.code} {date(year, month, 1):%B %Y}.'
        ))
