import random
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic import View
from .models import (
    UserSurveyProgress, LuckyDrawEntry, PollResponse, CountryLuckyDrawConfig,
    SurveyResponse, MonthlyDrawNumbers, MonthlyDrawSettlement, UserProfile, WalletTransaction,
    MonthlyDrawDay,
)
from django.db import transaction
from datetime import date, datetime, time, timedelta

# Draw days before this are never settled, so turning the payout on doesn't pay out retroactively.
MONTHLY_PAYOUT_FROM = date(2026, 10, 1)
from django.db.models import Sum, Count, F
import random
from django.utils import timezone
from django.http import JsonResponse  # Add this line
import json
from decimal import Decimal
from .emails import (
    send_lucky_draw_winner_email, send_lucky_draw_winner_admin_notification,
    send_monthly_draw_closed_admin_notification,
)


QUICK_DRAW_NUDGE = 'Please complete one more survey to qualify for the Quick draw.'


def monthly_draw_tz(country):
    """The clock a country's Monthly draw runs on (its config's time zone, else the site's)."""
    config = CountryLuckyDrawConfig.get_for_country(country)
    return config.tzinfo if config else timezone.get_current_timezone()


def month_bounds(tz, at=None):
    """(now, start of this month, start of next month), all on the `tz` clock."""
    now = timezone.localtime(at or timezone.now(), tz)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return now, month_start, next_month_start


def monthly_test_date():
    """LUCKY_DRAW_CONFIG['MONTHLY_DRAW_TEST_DATE'] as a date, or None."""
    value = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_DRAW_TEST_DATE')
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def is_monthly_draw_day(day):
    return day.day == 1 or day == monthly_test_date()


def previous_draw_day(draw_day):
    """The regular draw day (a 1st) before `draw_day`."""
    if draw_day.day == 1:
        return (draw_day - timedelta(days=1)).replace(day=1)
    return draw_day.replace(day=1)


def current_or_next_draw_day(today):
    """Today if it's a draw day, otherwise the next one (next 1st, or an upcoming test date)."""
    if is_monthly_draw_day(today):
        return today
    next_first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    test_date = monthly_test_date()
    return min(next_first, test_date) if test_date and test_date > today else next_first


def draw_cycle(draw_day, tz):
    """(start, end) of the qualifying period for `draw_day`, on the `tz` clock.

    Surveys completed from the day after the previous draw day up to the end of
    this draw day earn this draw's attempts, e.g. 2 Oct 00:00 - 2 Nov 00:00 for
    the 1 November draw (so October's surveys count). Attempts not used by the
    end of the draw day are gone: the next draw starts a new period.
    """
    start = datetime.combine(previous_draw_day(draw_day) + timedelta(days=1), time.min, tzinfo=tz)
    end = datetime.combine(draw_day + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def format_money(symbol, amount):
    amount = Decimal(amount)
    return f"{symbol}{int(amount) if amount == amount.to_integral() else f'{amount:.2f}'}"


class LuckyDrawView(View):
    def quick_draw_nudge(self, user):
        """Text to add to the survey "Thank you" message, or '' for none.

        Returned only when the user cannot play the Quick draw yet and exactly
        one more survey would qualify them. It is derived from the same eligibility
        the draw itself uses, so it can never disagree with when the draw
        actually unlocks. (Users who already qualify are sent straight to the
        draw, and users further away get no message.)
        """
        eligibility = self.get_eligibility_context(user)
        # Quick draw only: a Poll draw play or Monthly attempts waiting don't
        # change how many surveys the Quick draw still needs.
        if eligibility['survey_eligible']:
            return ''
        if eligibility['surveys_required'] - eligibility['surveys_completed'] == 1:
            return QUICK_DRAW_NUDGE
        return ''

    def get_user_country_config(self, user):
        profile = getattr(user, 'profile', None)
        country = getattr(profile, 'country', None)
        return CountryLuckyDrawConfig.get_for_country(country)

    def get_poll_requirement(self, user):
        settings_requirement = settings.LUCKY_DRAW_CONFIG.get('POLLS_REQUIRED')
        if settings_requirement is not None:
            return settings_requirement

        config = self.get_user_country_config(user)
        if config:
            return config.poll_count_required
        return 5

    def get_monthly_draw_config(self, user):
        """The user's country config if that country takes part in the Monthly draw."""
        config = self.get_user_country_config(user)
        if config and config.monthly_prize_amount is not None:
            return config
        return None

    def get_prize_amount_and_currency(self, user, draw_type=None):
        """(amount, currency_code, currency_symbol) for this user's country.

        CountryLuckyDrawConfig is the single source of truth when a row
        exists for the user's country; both the prize text shown on the page
        and the actual wallet credit are derived from it, so they can never
        disagree. The Monthly draw has its own prize on that row. Falls back to
        the historical Quick draw defaults when no config row exists.
        """
        if draw_type == LuckyDrawEntry.DRAW_TYPE_MONTHLY:
            monthly = self.get_monthly_draw_config(user)
            if monthly:
                return monthly.monthly_prize_amount, monthly.currency_code, monthly.currency_symbol

        config = self.get_user_country_config(user)
        if config:
            return config.prize_amount, config.currency_code, config.currency_symbol

        profile = getattr(user, 'profile', None)
        country_code = str(getattr(getattr(profile, 'country', None), 'code', '') or '').upper()
        if country_code in ['US', 'CA']:
            return Decimal('1.00'), 'USD', '$'
        if country_code == 'GB':
            return Decimal('1.00'), 'GBP', '£'
        if country_code == 'NG':
            return Decimal('0.50'), 'USD', '$'
        return Decimal('1.00'), 'USD', '$'

    def get_prize_for_user(self, user, draw_type=None):
        amount, currency_code, currency_symbol = self.get_prize_amount_and_currency(user, draw_type)
        amount_display = int(amount) if amount == amount.to_integral() else f"{amount:.2f}"
        return f"{currency_symbol}{amount_display} {currency_code}".strip()

    def get_monthly_winner_count(self, country, at=None):
        """Monthly draw winners so far this calendar month (country's own clock) for one country.

        No-draw payouts (guessed number 0) aren't draw winners, so they don't use up prizes.
        """
        _now, month_start, next_month_start = month_bounds(monthly_draw_tz(country), at)
        return LuckyDrawEntry.objects.filter(
            draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
            is_winner=True,
            created_at__gte=month_start,
            created_at__lt=next_month_start,
            user__profile__country=country,
        ).exclude(guessed_number=0).count()

    def earned_attempts_by_user(self, country, required, cycle, until=None):
        """{user_id: Monthly attempts earned in `cycle`} for every user in `country`.

        One attempt per `required`-survey milestone (100, 200, ...) crossed during
        the cycle: 200 surveys in the cycle = 2 attempts. Completions before the
        cycle come from SurveyResponse; the total "now" is the live survey count,
        or, with `until`, the completions before that moment (for settling a day
        that has ended).
        """
        start, _end = cycle
        completed = SurveyResponse.objects.filter(user__profile__country=country, completed_at__isnull=False)
        before = dict(completed.filter(completed_at__lt=start).values_list('user_id').annotate(c=Count('id')))
        if until is None:
            totals = {
                row['user_id']: row['total'] or 0
                for row in UserSurveyProgress.objects.filter(user__profile__country=country)
                .values('user_id').annotate(total=Sum('completed_count'))
            }
        else:
            totals = dict(completed.filter(completed_at__lt=until).values_list('user_id').annotate(c=Count('id')))
        earned = {
            user_id: total // required - before.get(user_id, 0) // required for user_id, total in totals.items()
        }
        return {user_id: n for user_id, n in earned.items() if n > 0}

    def get_monthly_qualified_attempts(self, country, required, cycle, until=None):
        """How many Monthly attempts the country's users earned in `cycle` (the minimum-5 count and board size N)."""
        return sum(self.earned_attempts_by_user(country, required, cycle, until).values())

    def monthly_attempts_used(self, user_id, cycle):
        """Monthly attempts used in `cycle`: plays, and attempts paid out when the draw didn't run."""
        start, end = cycle
        return LuckyDrawEntry.objects.filter(
            user_id=user_id, draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
            created_at__gte=start, created_at__lt=end,
        ).count()

    def get_monthly_cycle(self, config, at=None):
        """(draw_day, cycle) for the draw that's on today, or the next one, on the country's clock."""
        tz = config.tzinfo if config else timezone.get_current_timezone()
        today = timezone.localtime(at or timezone.now(), tz).date()
        draw_day = current_or_next_draw_day(today)
        return draw_day, draw_cycle(draw_day, tz)

    def get_monthly_winners(self, country, at=None):
        """This month's Monthly draw winners for one country, in the order they won."""
        _now, month_start, next_month_start = month_bounds(monthly_draw_tz(country), at)
        return LuckyDrawEntry.objects.filter(
            draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
            is_winner=True,
            created_at__gte=month_start,
            created_at__lt=next_month_start,
            user__profile__country=country,
        ).exclude(guessed_number=0).select_related('user').order_by('created_at', 'id')

    def format_winner_name(self, user):
        """"F. Surname" — same privacy convention as the homepage's recent-winners list."""
        full_name = user.get_full_name() or user.username
        name_parts = full_name.split()
        if len(name_parts) > 1:
            return f"{name_parts[0][0].upper()}. {' '.join(name_parts[1:])}"
        return full_name

    def format_winner_list(self, names):
        """"1: Name, 2: Name, ..." so a blocked player can see who took this month's slots."""
        return ', '.join(f"{position}: {name}" for position, name in enumerate(names, start=1))

    def credit_winner_wallet(self, entry):
        if not entry.is_winner:
            return Decimal('0.00')

        from django.db import transaction
        from django.db.models import F
        from .models import UserProfile, WalletTransaction

        if WalletTransaction.objects.filter(lucky_draw_entry=entry).exists():
            return Decimal('0.00')

        amount, currency_code, currency_symbol = self.get_prize_amount_and_currency(entry.user, entry.draw_type)
        with transaction.atomic():
            profile, _ = UserProfile.objects.select_for_update().get_or_create(user=entry.user)
            UserProfile.objects.filter(pk=profile.pk).update(wallet_balance=F('wallet_balance') + amount)
            profile.refresh_from_db(fields=['wallet_balance'])
            WalletTransaction.objects.create(
                profile=profile,
                transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
                amount=amount,
                currency_code=currency_code,
                currency_symbol=currency_symbol,
                description=f"{entry.get_draw_type_display()} lucky draw win",
                lucky_draw_entry=entry,
                balance_after=profile.wallet_balance,
            )
        return amount

    def get_completion_counts(self, user):
        total_surveys = user.survey_progress.aggregate(
            total=Sum('completed_count')
        )['total'] or 0
        total_polls = PollResponse.objects.filter(user=user).count()
        return total_surveys, total_polls

    def get_last_entry(self, user, draw_type):
        return user.lucky_draw_entries.filter(draw_type=draw_type).order_by('-created_at').first()

    def get_qualifying_survey(self, user, last_entry):
        queryset = SurveyResponse.objects.filter(
            user=user,
            completed_at__isnull=False,
        ).select_related('survey').order_by('-completed_at')
        if last_entry:
            queryset = queryset.filter(completed_at__gt=last_entry.created_at)
        response = queryset.first()
        return response.survey if response else None

    def get_qualifying_poll(self, user, last_entry):
        queryset = PollResponse.objects.filter(user=user).select_related('poll').order_by('-submitted_at')
        if last_entry:
            queryset = queryset.filter(submitted_at__gt=last_entry.created_at)
        response = queryset.first()
        return response.poll if response else None

    def get_monthly_eligibility(self, user, total_surveys):
        """Where the user stands in the Monthly draw.

        Attempts belong to a draw cycle (see draw_cycle): every
        MONTHLY_SURVEYS_REQUIRED surveys completed in the cycle is one attempt for
        that cycle's draw day, minus attempts already used in it. Nothing carries
        over to the next cycle. Only countries with a Monthly prize configured take
        part, each with its own prize and per-country winner cap.
        """
        config = self.get_monthly_draw_config(user)
        required = max(1, settings.LUCKY_DRAW_CONFIG.get('MONTHLY_SURVEYS_REQUIRED', 100))
        draw_day, cycle = self.get_monthly_cycle(config)
        before_cycle = SurveyResponse.objects.filter(
            user=user, completed_at__isnull=False, completed_at__lt=cycle[0],
        ).count()
        completed = max(0, total_surveys - before_cycle)
        earned = max(0, total_surveys // required - before_cycle // required) if config else 0
        plays = max(0, earned - self.monthly_attempts_used(user.id, cycle)) if config else 0

        cap = config.monthly_winner_cap if config else None
        winners = self.get_monthly_winner_count(config.country) if (config and cap) else 0
        is_open = not (cap and winners >= cap)

        # Who took this month's slots, so a blocked player can see who won
        # instead of just being told the prizes are gone. Only fetched once
        # the draw is actually closed for the cap.
        winner_names = (
            [self.format_winner_name(entry.user) for entry in self.get_monthly_winners(config.country)]
            if (config and cap and not is_open) else []
        )

        # The Monthly draw only runs on the 1st (or the test date), 00:00-23:59 on
        # the country's own clock.
        tz = config.tzinfo if config else timezone.get_current_timezone()
        today = timezone.localtime(timezone.now(), tz).date()
        window_open = is_monthly_draw_day(today)
        if window_open and today.day != 1:
            # A test draw day: remember it, so it's settled even after the setting moves on.
            MonthlyDrawDay.objects.get_or_create(draw_date=today)
        reopens_on = current_or_next_draw_day(today + timedelta(days=1)) if window_open else draw_day

        # The draw only runs if the country's users earned at least
        # MONTHLY_MIN_QUALIFIERS attempts this cycle (200 surveys = 2 of them).
        # Only checked (it's a whole-country scan) while the draw window is open.
        min_qualifiers = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_MIN_QUALIFIERS', 5)
        milestone_qualifiers = (
            self.get_monthly_qualified_attempts(config.country, required, cycle)
            if (config and min_qualifiers and window_open) else 0
        )
        quorum_met = (not min_qualifiers) or (not window_open) or (milestone_qualifiers >= min_qualifiers)
        payout = (config.monthly_prize_amount or 0) * plays if config else 0

        return {
            'monthly_available': config is not None,
            'monthly_required': required,
            'monthly_surveys_completed': completed,
            'monthly_progress_to_next': total_surveys % required,
            'monthly_plays_available': plays,
            'monthly_attempts_earned': earned,
            'monthly_draw_day': draw_day,
            'monthly_cycle': cycle,
            'monthly_payout_display': format_money(config.currency_symbol, payout) if config else '',
            'monthly_winner_cap': cap,
            'monthly_winners_this_month': winners,
            'monthly_winner_names': winner_names,
            'monthly_winner_list': self.format_winner_list(winner_names),
            'monthly_open': is_open,
            'monthly_window_open': window_open,
            'monthly_min_qualifiers': min_qualifiers,
            'monthly_milestone_qualifiers': milestone_qualifiers,
            'monthly_quorum_met': quorum_met,
            'monthly_eligible': plays > 0 and is_open and window_open and quorum_met,
            'monthly_resets_on': reopens_on,
            'monthly_prize_display': config.get_monthly_prize_display() if config else '',
        }

    def get_eligibility_context(self, user):
        last_entry = user.lucky_draw_entries.order_by('-created_at').first()
        last_survey_entry = self.get_last_entry(user, LuckyDrawEntry.DRAW_TYPE_SURVEY)
        last_poll_entry = self.get_last_entry(user, LuckyDrawEntry.DRAW_TYPE_POLL)
        total_surveys, total_polls = self.get_completion_counts(user)
        surveys_required = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
        polls_required = self.get_poll_requirement(user)

        surveys_completed = max(0, total_surveys - (last_survey_entry.surveys_at_play or 0)) if last_survey_entry else total_surveys
        polls_completed = max(0, total_polls - (last_poll_entry.polls_at_play or 0)) if last_poll_entry else total_polls
        survey_eligible = surveys_completed >= surveys_required
        poll_eligible = polls_completed >= polls_required

        # How many plays the user has earned but not yet used (catches up missed plays from errors)
        survey_plays_available = surveys_completed // surveys_required if survey_eligible else 0
        poll_plays_available = polls_completed // polls_required if poll_eligible else 0

        monthly = self.get_monthly_eligibility(user, total_surveys)

        eligible_draw_types = []
        if survey_eligible:
            eligible_draw_types.append(LuckyDrawEntry.DRAW_TYPE_SURVEY)
        if poll_eligible:
            eligible_draw_types.append(LuckyDrawEntry.DRAW_TYPE_POLL)
        if monthly['monthly_eligible']:
            eligible_draw_types.append(LuckyDrawEntry.DRAW_TYPE_MONTHLY)

        return {
            'last_entry': last_entry,
            'last_survey_entry': last_survey_entry,
            'last_poll_entry': last_poll_entry,
            'total_surveys': total_surveys,
            'total_polls': total_polls,
            'surveys_completed': surveys_completed,
            'polls_completed': polls_completed,
            'surveys_required': surveys_required,
            'polls_required': polls_required,
            'survey_eligible': survey_eligible,
            'poll_eligible': poll_eligible,
            'survey_plays_available': survey_plays_available,
            'poll_plays_available': poll_plays_available,
            'eligible_draw_types': eligible_draw_types,
            'user_eligible': bool(eligible_draw_types),
            **monthly,
        }

    def get_monthly_profile_stats(self, user):
        """Monthly Draw milestone figures shared by the profile and dashboard."""
        eligibility = self.get_eligibility_context(user)
        profile = getattr(user, 'profile', None)
        if not eligibility['monthly_available'] or not getattr(profile, 'country_id', None):
            return None

        required = eligibility['monthly_required']
        # Same count the draw's minimum-qualifiers rule uses: attempts earned this cycle.
        qualified_users = self.get_monthly_qualified_attempts(profile.country, required, eligibility['monthly_cycle'])
        milestone_users = self.get_monthly_milestone_user_count(profile.country_id, required)
        total_completed = eligibility['total_surveys']
        return {
            'required': required,
            'total_completed': total_completed,
            'milestones_completed': total_completed // required,
            'attempts_available': eligibility['monthly_plays_available'],
            'qualified_users': qualified_users,
            'min_qualifiers': eligibility['monthly_min_qualifiers'],
            'milestone_users': milestone_users,
        }

    def get_monthly_period(self, config):
        """(year, month, month_start, next_month_start) for this month on the country's clock."""
        _now, month_start, next_month_start = month_bounds(config.tzinfo)
        return month_start.year, month_start.month, month_start, next_month_start

    def get_monthly_numbers(self, config, board_size=None):
        """This month's MonthlyDrawNumbers row for the country.

        With `board_size`, draws the winning numbers (as many as the winner cap,
        default 4) from 1..board_size the first time it's asked; otherwise only
        returns an existing row, or None.
        """
        year, month, _start, _next = self.get_monthly_period(config)
        lookup = {'country': config.country, 'year': year, 'month': month}
        if board_size is None:
            return MonthlyDrawNumbers.objects.filter(**lookup).first()
        count = min(config.monthly_winner_cap or 4, board_size)

        def draw():
            return sorted(random.sample(range(1, board_size + 1), count))

        numbers, created = MonthlyDrawNumbers.objects.get_or_create(**lookup, defaults={'winning_numbers': draw()})
        # Numbers drawn before N was this month's milestone count can lie outside
        # 1..N; redraw them, but only while nobody has picked a number yet.
        if not created and max(numbers.winning_numbers, default=0) > board_size and not self.get_monthly_picks(config):
            numbers.winning_numbers = draw()
            numbers.save(update_fields=['winning_numbers'])
        return numbers

    def get_monthly_picks(self, config):
        """{number: entry} for every Monthly number already picked in the country this month."""
        _year, _month, month_start, next_month_start = self.get_monthly_period(config)
        entries = LuckyDrawEntry.objects.filter(
            draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
            created_at__gte=month_start,
            created_at__lt=next_month_start,
            user__profile__country=config.country,
        ).select_related('user').order_by('created_at', 'id')
        picks = {}
        for entry in entries:
            picks.setdefault(entry.guessed_number, entry)
        return picks

    def get_monthly_winning_display(self, config):
        """This month's winning numbers for the page, each with who won it (if anyone)."""
        numbers = self.get_monthly_numbers(config)
        if not numbers:
            return []
        picks = self.get_monthly_picks(config)
        return [
            {
                'number': n,
                'won_by': self.format_winner_name(picks[n].user) if n in picks and picks[n].is_winner else '',
            }
            for n in numbers.winning_numbers
        ]

    def monthly_draw_days_to_settle(self, config):
        """Ended Monthly draw days not yet settled: the 1st of this and last month,
        the current test date, and every earlier test date the draw opened on
        (recorded in MonthlyDrawDay, so moving the test date on doesn't skip a day).
        """
        now, month_start, _next = month_bounds(config.tzinfo)
        days = {month_start.date(), (month_start - timedelta(days=1)).replace(day=1).date()}
        test_date = monthly_test_date()
        if test_date:
            days.add(test_date)
        days.update(MonthlyDrawDay.objects.filter(
            draw_date__gte=now.date() - timedelta(days=40),
        ).values_list('draw_date', flat=True))
        settled = set(MonthlyDrawSettlement.objects.filter(
            country=config.country, draw_date__in=days,
        ).values_list('draw_date', flat=True))
        return sorted(d for d in days if MONTHLY_PAYOUT_FROM <= d < now.date() and d not in settled)

    def settle_due_monthly_draws(self, config):
        for draw_date in self.monthly_draw_days_to_settle(config):
            self.settle_monthly_draw(config, draw_date)

    def settle_monthly_draw(self, config, draw_date):
        """Settle one ended draw day for a country, once, and email the admin its outcome.

        If the country's users earned fewer than MONTHLY_MIN_QUALIFIERS attempts
        in the draw's cycle (counted from completed surveys up to the end of the
        day, so later surveys don't change it), the draw didn't run: every
        attempt still unused is paid the Monthly prize, so 2 unused attempts =
        2 x the prize, and those attempts are used up.
        """
        settlement, created = self._settle_monthly_draw(config, draw_date)
        if created:
            try:
                summary = self.monthly_draw_day_summary(config, settlement)
                # Days where nobody qualified or played have nothing to report.
                if summary['qualifiers'] or summary['plays'] or summary['payouts']:
                    send_monthly_draw_closed_admin_notification(summary)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Failed to send Monthly draw closed email')
        return settlement

    def monthly_draw_day_summary(self, config, settlement):
        """What happened on one settled draw day, for the admin email."""
        tz = config.tzinfo
        day_start = datetime.combine(settlement.draw_date, time.min, tzinfo=tz)
        day_end = datetime.combine(settlement.draw_date + timedelta(days=1), time.min, tzinfo=tz)
        entries = LuckyDrawEntry.objects.filter(
            draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY, user__profile__country=config.country,
            created_at__gte=day_start, created_at__lt=day_end,
        ).select_related('user').order_by('created_at', 'id')
        plays = [e for e in entries if e.guessed_number != 0]
        winners = [
            {'name': e.user.get_full_name() or e.user.username, 'email': e.user.email,
             'number': e.guessed_number, 'prize': e.prize}
            for e in plays if e.is_winner
        ]
        payouts_by_user = {}
        for e in entries:
            if e.guessed_number == 0:
                payouts_by_user.setdefault(e.user, 0)
                payouts_by_user[e.user] += 1
        prize = config.monthly_prize_amount or 0
        payouts = [
            {'name': user.get_full_name() or user.username, 'email': user.email, 'attempts': n,
             'amount': format_money(config.currency_symbol, prize * n)}
            for user, n in payouts_by_user.items()
        ]
        numbers = MonthlyDrawNumbers.objects.filter(
            country=config.country, year=settlement.draw_date.year, month=settlement.draw_date.month,
        ).first()
        won = {e.guessed_number for e in plays if e.is_winner}
        return {
            'country': config.country,
            'draw_date': settlement.draw_date,
            'time_zone': config.time_zone,
            'qualifiers': settlement.qualifiers,
            'min_qualifiers': settings.LUCKY_DRAW_CONFIG.get('MONTHLY_MIN_QUALIFIERS', 5),
            'quorum_met': settlement.quorum_met,
            'plays': len(plays),
            'winners': winners,
            'winning_numbers': [{'number': n, 'won': n in won} for n in (numbers.winning_numbers if numbers else [])],
            'prize': config.get_monthly_prize_display(),
            'payouts': payouts,
            'payout_total': format_money(config.currency_symbol, prize * sum(payouts_by_user.values())),
        }

    def _settle_monthly_draw(self, config, draw_date):
        """settle_monthly_draw's work: returns (settlement, created)."""
        existing = MonthlyDrawSettlement.objects.filter(country=config.country, draw_date=draw_date).first()
        if existing:
            return existing, False

        tz = config.tzinfo
        required = max(1, settings.LUCKY_DRAW_CONFIG.get('MONTHLY_SURVEYS_REQUIRED', 100))
        min_qualifiers = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_MIN_QUALIFIERS', 5)
        cycle = draw_cycle(draw_date, tz)
        day_end = cycle[1]

        earned = self.earned_attempts_by_user(config.country, required, cycle, until=day_end)
        qualifiers = sum(earned.values())
        quorum_met = (not min_qualifiers) or qualifiers >= min_qualifiers

        with transaction.atomic():
            settlement, created = MonthlyDrawSettlement.objects.get_or_create(
                country=config.country, draw_date=draw_date,
                defaults={'qualifiers': qualifiers, 'quorum_met': quorum_met},
            )
            if not created:
                return settlement, False
            if quorum_met or config.monthly_prize_amount is None:
                return settlement, True

            amount = config.monthly_prize_amount
            paid = 0
            for user_id, attempts in earned.items():
                unused = attempts - self.monthly_attempts_used(user_id, cycle)
                if unused < 1:
                    continue
                surveys_before_end = SurveyResponse.objects.filter(
                    user_id=user_id, completed_at__isnull=False, completed_at__lt=day_end,
                ).count()
                for _ in range(unused):
                    entry = LuckyDrawEntry.objects.create(
                        user_id=user_id, draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
                        guessed_number=0, winning_number=0, is_winner=True,
                        prize=f'{config.get_monthly_prize_display()} (no draw)',
                        surveys_at_play=surveys_before_end,
                        polls_at_play=PollResponse.objects.filter(user_id=user_id).count(),
                    )
                    # Dated within the draw day, so it uses up this cycle's attempt and no later one.
                    LuckyDrawEntry.objects.filter(pk=entry.pk).update(created_at=day_end - timedelta(seconds=1))
                    profile = UserProfile.objects.select_for_update().get(user_id=user_id)
                    UserProfile.objects.filter(pk=profile.pk).update(wallet_balance=F('wallet_balance') + amount)
                    profile.refresh_from_db(fields=['wallet_balance'])
                    WalletTransaction.objects.create(
                        profile=profile,
                        transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
                        amount=amount,
                        currency_code=config.currency_code,
                        currency_symbol=config.currency_symbol,
                        description=(
                            f'Monthly draw prize - draw did not run ({qualifiers} of {min_qualifiers} qualified)'
                        ),
                        lucky_draw_entry=entry,
                        balance_after=profile.wallet_balance,
                    )
                paid += 1
            settlement.paid_users = paid
            settlement.save(update_fields=['paid_users'])
        return settlement, True

    def get_monthly_milestone_user_count(self, country_id, required):
        """Users in a country who have completed at least `required` surveys.

        Shown on the profile/dashboard as "Users Reached Monthly Milestone" and
        used as N for the Monthly draw board (numbers 1 to N).
        """
        return (
            UserSurveyProgress.objects
            .filter(user__profile__country_id=country_id)
            .values('user_id')
            .annotate(total_completed=Sum('completed_count'))
            .filter(total_completed__gte=required)
            .count()
        )

    def monthly_play_error(self, user):
        """Why the user cannot play the Monthly draw right now, or '' if they can."""
        e = self.get_eligibility_context(user)
        if not e['monthly_available']:
            return 'The Monthly draw is not available in your country.'
        if not e['monthly_window_open']:
            resets_on = e['monthly_resets_on']
            return (
                "The Monthly draw only runs on the 1st of each month. "
                f"It opens again on {resets_on.strftime('%B')} {resets_on.day}."
            )
        if not e['monthly_quorum_met']:
            return (
                f"Not enough people have reached the {e['monthly_required']}-survey milestone in your "
                f"country this month yet (at least {e['monthly_min_qualifiers']} users needed for monthly "
                f"surveys to run) — there's no monthly draw this cycle."
                + (f" Your {e['monthly_payout_display']} will be automatically added to your wallet"
                   if e['monthly_plays_available'] else '')
            )
        if not e['monthly_open']:
            message = "All of this month's Monthly draw prizes for your country have been won."
            if e['monthly_winner_list']:
                message += f" Winners: {e['monthly_winner_list']}."
            return message
        if not e['monthly_plays_available']:
            return f"You need to complete {e['monthly_required']} surveys for a Monthly draw attempt."
        return ''

    def resolve_draw_type(self, user, requested_draw_type=None):
        if requested_draw_type in LuckyDrawEntry.VALID_DRAW_TYPES:
            return requested_draw_type

        eligible_draw_types = self.get_eligibility_context(user)['eligible_draw_types']
        if eligible_draw_types:
            return eligible_draw_types[0]
        return LuckyDrawEntry.DRAW_TYPE_SURVEY

    def get(self, request, *args, **kwargs):
        # Check if this is a request for the lucky number
        if request.path.endswith('/number/'):
            return self.get_lucky_number(request)

        # Backup for the scheduled settle_monthly_draws job: pay out the user's
        # country for any ended draw day that couldn't run, before showing attempts.
        monthly_config = self.get_monthly_draw_config(request.user)
        if monthly_config:
            self.settle_due_monthly_draws(monthly_config)
        
        # Get current month and year for play check
        current_date = timezone.now()
        current_month = current_date.month
        current_year = current_date.year
        
        # Check if user has already played this month
        has_played = LuckyDrawEntry.objects.filter(
            user=request.user,
            created_at__month=current_month,
            created_at__year=current_year
        ).exists()
        
        eligibility = self.get_eligibility_context(request.user)
        last_entry = eligibility['last_entry']
        last_quick_entry = request.user.lucky_draw_entries.filter(
            draw_type__in=(LuckyDrawEntry.DRAW_TYPE_SURVEY, LuckyDrawEntry.DRAW_TYPE_POLL),
        ).order_by('-created_at').first()
        
        # Get current month's winning number
        current_winner = LuckyDrawEntry.objects.filter(
            created_at__month=current_month,
            created_at__year=current_year,
            is_winner=True
        ).order_by('-created_at').first()
        
        total_surveys = eligibility['total_surveys']
        total_polls = eligibility['total_polls']
        surveys_completed = eligibility['surveys_completed']
        polls_completed = eligibility['polls_completed']
        surveys_required = eligibility['surveys_required']
        polls_required = eligibility['polls_required']
        user_eligible = eligibility['user_eligible']
        survey_eligible = eligibility['survey_eligible']
        poll_eligible = eligibility['poll_eligible']
        
        # Debug output
        print("\n=== Lucky Draw Debug Info ===")
        print(f"Total Surveys: {total_surveys}")
        print(f"Total Polls: {total_polls}")
        print(f"Surveys Since Last Play: {surveys_completed}")
        print(f"Polls Since Last Play: {polls_completed}")
        print(f"Surveys Required: {surveys_required}")
        print(f"Polls Required: {polls_required}")
        print(f"User Eligible: {user_eligible}")
        if last_entry:
            print(f"Last Play: {last_entry.created_at}")
            print(f"Surveys at Last Play: {last_entry.surveys_at_play}")
        print("==========================\n")
        
        # Generate number range from settings
        number_range = list(range(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END'] + 1
        ))
        random.shuffle(number_range)

        # Generate lucky number
        current_lucky_number = random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )

        # Store both in the session — never expose them in the HTML
        request.session['lucky_draw_grid'] = number_range
        request.session['lucky_draw_number'] = current_lucky_number

        # The Monthly draw gets its own board: numbers 1 to N, where N is how many
        # users in the player's country reached the Monthly milestone this month. The
        # country's winning numbers for the month are shared and shown on the page;
        # numbers already picked by anyone are shown blocked. Which hidden box holds
        # which remaining number lives only in the session. With fewer than 2
        # milestone users it falls back to the board above.
        monthly_range = []
        monthly_taken = []
        request.session.pop('lucky_draw_grid_monthly', None)
        request.session.pop('lucky_draw_number_monthly', None)
        monthly_config = self.get_monthly_draw_config(request.user)
        if eligibility['monthly_eligible'] and monthly_config:
            board_size = self.get_monthly_qualified_attempts(
                monthly_config.country, eligibility['monthly_required'], eligibility['monthly_cycle'],
            )
            if board_size >= 2:
                numbers = self.get_monthly_numbers(monthly_config, board_size)
                picks = self.get_monthly_picks(monthly_config)
                board_size = max([board_size, *numbers.winning_numbers, *picks])
                monthly_taken = [
                    {'number': n, 'winning': n in numbers.winning_numbers} for n in sorted(picks)
                ]
                monthly_range = [n for n in range(1, board_size + 1) if n not in picks]
                random.shuffle(monthly_range)
                request.session['lucky_draw_grid_monthly'] = monthly_range

        survey_plays_available = eligibility['survey_plays_available']
        poll_plays_available = eligibility['poll_plays_available']
        monthly_plays_playable = (
            eligibility['monthly_plays_available']
            if (eligibility['monthly_open'] and eligibility['monthly_window_open'] and eligibility['monthly_quorum_met']) else 0
        )
        total_plays_available = survey_plays_available + poll_plays_available + monthly_plays_playable

        context = {
            'LUCKY_DRAW_CONFIG': {
                **settings.LUCKY_DRAW_CONFIG,
                # NUMBER_RANGE is intentionally excluded — stored in session only
            },
            # grid_range gives the template a safe index sequence (no actual numbers)
            'grid_range': range(len(number_range)),
            'monthly_grid_range': range(len(monthly_range)),
            'monthly_taken_numbers': monthly_taken,
            'monthly_winning_numbers': self.get_monthly_winning_display(monthly_config) if monthly_config else [],
            # testing_numbered_grid/testing_winning_number are ONLY populated when
            # SHOW_NUMBERS_FOR_TESTING is on — must stay False/unset in production.
            'user_eligible': user_eligible,
            'survey_eligible': survey_eligible,
            'poll_eligible': poll_eligible,
            'eligible_draw_types': eligibility['eligible_draw_types'],
            'selected_draw_type': eligibility['eligible_draw_types'][0] if eligibility['eligible_draw_types'] else '',
            'surveys_completed': surveys_completed,
            'polls_completed': polls_completed,
            'surveys_required': surveys_required,
            'polls_required': polls_required,
            'survey_plays_available': survey_plays_available,
            'poll_plays_available': poll_plays_available,
            'total_plays_available': total_plays_available,
            # current_lucky_number is intentionally excluded — stored in session only
            'current_winner': current_winner,
            'last_play_date': last_quick_entry.created_at if last_quick_entry else None,
            # Each draw's last result is shown in its own area, so a Quick/Poll
            # loss never appears beside the Monthly draw (and vice versa).
            'last_quick_result': last_quick_entry if not user_eligible else None,
            'last_monthly_result': self.get_last_entry(request.user, LuckyDrawEntry.DRAW_TYPE_MONTHLY),
            'prize_display': self.get_prize_for_user(request.user),
        }

        # Monthly draw status for the page (attempts, prize, winners so far, whether open).
        context.update({key: value for key, value in eligibility.items() if key.startswith('monthly_')})

        # Testing-only: reveal the actual numbers so a tester can pick the
        # winning one without guessing. Gated by LUCKY_DRAW_CONFIG so it can
        # never leak in production once the flag is set back to False.
        if settings.LUCKY_DRAW_CONFIG.get('SHOW_NUMBERS_FOR_TESTING'):
            context['testing_numbered_grid'] = list(enumerate(number_range))
            context['testing_winning_number'] = current_lucky_number
            if monthly_range:
                context['testing_monthly_numbered_grid'] = list(enumerate(monthly_range))

        return render(request, 'surveys/lucky_draw.html', context)

    def get_lucky_number(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Not authenticated'}, status=401)

        draw_type = self.resolve_draw_type(request.user, request.GET.get('draw_type'))
        # Check if user is eligible to play
        if not self.is_eligible(request.user, draw_type):
            required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
            required_polls = self.get_poll_requirement(request.user)
            return JsonResponse({
                'error': f'You need to complete {required_surveys} surveys or {required_polls} polls to play the lucky draw.'
            }, status=400)
        
        # Generate a new lucky number
        lucky_number = random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )
        
        return JsonResponse({'lucky_number': lucky_number})

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Not authenticated'}, status=401)
            
        
        
       
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid request'}, status=400)

        requested_draw_type = data.get('draw_type')
        if requested_draw_type and requested_draw_type not in LuckyDrawEntry.VALID_DRAW_TYPES:
            return JsonResponse({'error': 'Invalid lucky draw type.'}, status=400)
        draw_type = self.resolve_draw_type(request.user, requested_draw_type)

        # Check if user is eligible to play for the selected source.
        if draw_type == LuckyDrawEntry.DRAW_TYPE_MONTHLY:
            monthly_error = self.monthly_play_error(request.user)
            if monthly_error:
                return JsonResponse({'error': monthly_error}, status=400)
        elif not self.is_eligible(request.user, draw_type):
            required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
            required_polls = self.get_poll_requirement(request.user)
            return JsonResponse({
                'error': f'You need to complete {required_surveys} surveys or {required_polls} polls to play again.'
            }, status=400)

        # Resolve the actual number from the session grid using the client-sent index.
        # The grid and lucky number are never sent to the browser, so they cannot
        # be tampered with from the client side.
        # A Monthly play uses its own 1-to-N board when the page built one.
        uses_monthly_board = (
            draw_type == LuckyDrawEntry.DRAW_TYPE_MONTHLY and 'lucky_draw_grid_monthly' in request.session
        )
        grid_key = 'lucky_draw_grid_monthly' if uses_monthly_board else 'lucky_draw_grid'
        grid = request.session.get(grid_key)
        if not grid:
            return JsonResponse({'error': 'Session expired. Please refresh the page.'}, status=400)

        try:
            index = int(data.get('index'))
            if not (0 <= index < len(grid)):
                raise ValueError('Invalid index')
            number = grid[index]
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid selection'}, status=400)
        
        total_surveys, total_polls = self.get_completion_counts(request.user)
        eligibility = self.get_eligibility_context(request.user)
        last_survey_entry = eligibility['last_survey_entry']
        last_poll_entry = eligibility['last_poll_entry']
        surveys_required = eligibility['surveys_required']
        polls_required = eligibility['polls_required']

        last_entry = self.get_last_entry(request.user, draw_type)
        qualifying_survey = None
        qualifying_poll = None
        if draw_type in (LuckyDrawEntry.DRAW_TYPE_SURVEY, LuckyDrawEntry.DRAW_TYPE_MONTHLY):
            qualifying_survey = self.get_qualifying_survey(request.user, last_entry)
        else:
            qualifying_poll = self.get_qualifying_poll(request.user, last_entry)

        # Advance the snapshot by exactly one required batch (not the full total).
        # This ensures any surplus completions carry over so the user can play
        # again immediately if they accumulated enough for multiple plays
        # (e.g. missed a play due to a server error).
        if draw_type == LuckyDrawEntry.DRAW_TYPE_SURVEY:
            surveys_baseline = last_survey_entry.surveys_at_play if last_survey_entry else 0
            entry_surveys_at_play = surveys_baseline + surveys_required
            entry_polls_at_play = total_polls
        elif draw_type == LuckyDrawEntry.DRAW_TYPE_MONTHLY:
            # The Monthly draw keeps its own snapshot: one attempt uses up
            # MONTHLY_SURVEYS_REQUIRED surveys, and any surplus carries over.
            monthly_baseline = last_entry.surveys_at_play if last_entry else 0
            entry_surveys_at_play = monthly_baseline + eligibility['monthly_required']
            entry_polls_at_play = total_polls
        else:
            polls_baseline = last_poll_entry.polls_at_play if last_poll_entry else 0
            entry_polls_at_play = polls_baseline + polls_required
            entry_surveys_at_play = total_surveys

        entry_fields = {
            'user': request.user,
            'draw_type': draw_type,
            'survey': qualifying_survey,
            'poll': qualifying_poll,
            'guessed_number': number,
            'surveys_at_play': entry_surveys_at_play,
            'polls_at_play': entry_polls_at_play,
        }
        monthly_winning_numbers = None

        if uses_monthly_board:
            # Shared Monthly board: the winning numbers are the country's for the
            # month, and each number can be picked once. The row lock makes two
            # players clicking the same number at once resolve to one of them.
            for key in ('lucky_draw_grid', 'lucky_draw_number', 'lucky_draw_grid_monthly', 'lucky_draw_number_monthly'):
                request.session.pop(key, None)
            config = self.get_monthly_draw_config(request.user)
            year, month, _start, _next = self.get_monthly_period(config)
            with transaction.atomic():
                numbers = MonthlyDrawNumbers.objects.select_for_update().filter(
                    country=config.country, year=year, month=month,
                ).first()
                if numbers is None:
                    return JsonResponse({'error': 'Session expired. Please refresh the page.'}, status=400)
                if number in self.get_monthly_picks(config):
                    return JsonResponse({
                        'error': f'Number {number} has just been picked by another player. '
                                 'Please refresh and choose another number.'
                    }, status=409)
                monthly_winning_numbers = numbers.winning_numbers
                is_winner = number in monthly_winning_numbers
                prize = self.get_prize_for_user(request.user, draw_type) if is_winner else None
                entry = LuckyDrawEntry.objects.create(
                    **entry_fields,
                    winning_number=number if is_winner else monthly_winning_numbers[0],
                    is_winner=is_winner,
                    prize=prize,
                )
        else:
            # Winning number comes from the session — never from the client request
            winning_number = request.session.get('lucky_draw_number')
            if winning_number is None:
                return JsonResponse({'error': 'Session expired. Please refresh the page.'}, status=400)

            # Invalidate both session boards so this draw cannot be replayed
            for key in ('lucky_draw_grid', 'lucky_draw_number', 'lucky_draw_grid_monthly', 'lucky_draw_number_monthly'):
                request.session.pop(key, None)

            is_winner = (number == winning_number)
            prize = self.get_prize_for_user(request.user, draw_type) if is_winner else None
            entry = LuckyDrawEntry.objects.create(
                **entry_fields, winning_number=winning_number, is_winner=is_winner, prize=prize,
            )
        
        # Send email notifications if user won
        if is_winner:
            self.credit_winner_wallet(entry)
            try:
                # Send winner email to user
                
                send_lucky_draw_winner_email(entry)
                send_lucky_draw_winner_admin_notification(entry)
                print(f"Winner emails sent to {entry.user.email} and admin")
            except Exception as e:
                # Log the error but don't fail the request
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to send winner emails: {str(e)}")
                print(f"Error sending winner emails: {str(e)}")
        
        post_play_eligibility = self.get_eligibility_context(request.user)
        remaining_draw_types = post_play_eligibility['eligible_draw_types']
        plays_remaining = (
            post_play_eligibility['survey_plays_available']
            + post_play_eligibility['poll_plays_available']
            + (
                post_play_eligibility['monthly_plays_available']
                if (
                    post_play_eligibility['monthly_open']
                    and post_play_eligibility['monthly_window_open']
                    and post_play_eligibility['monthly_quorum_met']
                ) else 0
            )
        )

        return JsonResponse({
            'is_winner': is_winner,
            'guessed_number': number,
            'winning_number': entry.winning_number,
            'winning_numbers': monthly_winning_numbers,
            'prize': prize,
            'draw_type': draw_type,
            'remaining_draw_types': remaining_draw_types,
            'plays_remaining': plays_remaining,
            # Plays left for the draw just played only, so a Monthly result never counts Quick plays.
            'draw_plays_remaining': {
                LuckyDrawEntry.DRAW_TYPE_SURVEY: post_play_eligibility['survey_plays_available'],
                LuckyDrawEntry.DRAW_TYPE_POLL: post_play_eligibility['poll_plays_available'],
                LuckyDrawEntry.DRAW_TYPE_MONTHLY: (
                    post_play_eligibility['monthly_plays_available']
                    if post_play_eligibility['monthly_eligible'] else 0
                ),
            }[draw_type],
        })

    def is_eligible(self, user, draw_type=None):
        """
        Check if the user is eligible to play the lucky draw.
        A user is eligible if they have completed the required number of surveys
        since their last play (or since they started if they've never played).
        """
        if not user.is_authenticated:
            print("User not authenticated")
            return False
        
        # Get the last entry if it exists
        last_entry = user.lucky_draw_entries.order_by('-created_at').first()
        eligibility = self.get_eligibility_context(user)
        total_surveys = eligibility['total_surveys']
        total_polls = eligibility['total_polls']
        required_surveys = eligibility['surveys_required']
        required_polls = eligibility['polls_required']

        if draw_type == LuckyDrawEntry.DRAW_TYPE_SURVEY:
            return eligibility['survey_eligible']
        if draw_type == LuckyDrawEntry.DRAW_TYPE_POLL:
            return eligibility['poll_eligible']
        if draw_type == LuckyDrawEntry.DRAW_TYPE_MONTHLY:
            return eligibility['monthly_eligible']
        
        # If user has never played, check if they've completed the required surveys
        if not last_entry:
            is_eligible = eligibility['user_eligible']
            print(f"User has never played. Eligible: {is_eligible} (surveys: {total_surveys}/{required_surveys}, polls: {total_polls}/{required_polls})")
            return is_eligible
        
        # Calculate surveys completed since last play
        surveys_since_last_play = eligibility['surveys_completed']
        polls_since_last_play = eligibility['polls_completed']
        is_eligible = eligibility['user_eligible']
        
        print(f"Eligibility check:")
        print(f"- Total surveys: {total_surveys}")
        print(f"- Total polls: {total_polls}")
        print(f"- Surveys at last play: {last_entry.surveys_at_play}")
        print(f"- Polls at last play: {last_entry.polls_at_play}")
        print(f"- Surveys since last play: {surveys_since_last_play}")
        print(f"- Polls since last play: {polls_since_last_play}")
        print(f"- Required surveys: {required_surveys}")
        print(f"- Required polls: {required_polls}")
        print(f"- Is eligible: {is_eligible}")
        
        return is_eligible

    @classmethod
    def update_survey_progress(cls, survey, user):
        from django.db.models import F
        
        # Get or create user's progress for this category and level
        progress, created = UserSurveyProgress.objects.get_or_create(
            user=user,
            category=survey.category,
            level=survey.level,
            defaults={'completed_count': 1}
        )
        
        if not created:
            # Use F() to prevent race conditions
            progress.completed_count = F('completed_count') + 1
            progress.save(update_fields=['completed_count', 'last_completed'])
            progress.refresh_from_db()  # Get the updated count
