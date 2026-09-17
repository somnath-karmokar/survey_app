from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from decimal import Decimal

from .emails import (
    send_milestone_achievement_admin_notification,
    send_milestone_achievement_email,
)
from .models import MilestoneAchievement, PollResponse, SurveyResponse, UserProfile, WalletTransaction


DEFAULT_MILESTONE_CONFIG = (
    {
        'milestone_type': 'surveys_completed',
        'threshold': 100,
        'prize_name': 'Wallet Reward',
        'repeat_interval': 100,
        'wallet_reward': True,
        'wallet_reward_amount': Decimal('1.00'),  # $1 / £1 per 100 surveys
        'excluded_countries': ('NG',),  # no survey milestones for Nigeria
    },
    # polls_completed and points_earned milestones are paused - only the
    # surveys_completed milestone above is currently active. Re-add an entry
    # here (see MILESTONE_REWARDS in settings.py) to switch one back on.
)


def get_user_milestone_stats(user):
    completed_surveys = SurveyResponse.objects.filter(
        user=user,
        completed_at__isnull=False,
    ).count()
    completed_polls = PollResponse.objects.filter(user=user).count()
    points_earned = completed_surveys * 10
    return {
        'surveys_completed': completed_surveys,
        'polls_completed': completed_polls,
        'points_earned': points_earned,
    }


def get_user_country_code(user):
    profile = getattr(user, 'profile', None)
    return str(getattr(getattr(profile, 'country', None), 'code', '') or '').upper()


def is_milestone_excluded_for_user(user_country_code, milestone):
    """True when this milestone should not apply to a user with this country.

    A milestone with `excluded_countries` set excludes both a listed country
    (e.g. Nigeria) and a user with no country on file at all - we don't know
    which currency/rules would apply to them, so they are held out rather
    than assumed eligible. A milestone with no `excluded_countries` applies
    to everyone, including users with no country set.
    """
    excluded_countries = milestone.get('excluded_countries') or ()
    if not excluded_countries:
        return False
    return (not user_country_code) or (user_country_code in excluded_countries)


def milestone_rewards_enabled():
    """Milestone payouts are off for now (see MILESTONE_REWARDS_ENABLED).

    Kept behind a flag rather than deleted so existing achievements stay
    readable in the admin and payouts can be switched back on later.
    """
    return getattr(settings, 'MILESTONE_REWARDS_ENABLED', True)


def get_milestone_config():
    if not milestone_rewards_enabled():
        return ()
    return getattr(settings, 'MILESTONE_REWARDS', DEFAULT_MILESTONE_CONFIG)


def get_wallet_reward_display(user, amount=None):
    """The reward amount + the user's wallet currency (USD, or GBP for GB).

    `amount` lets a specific milestone override the default $2.00 - the
    surveys_completed milestone pays $1 / £1 per 100 surveys, for instance.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)
    amount = amount if amount is not None else Decimal('2.00')
    return amount, profile.wallet_currency_code, profile.wallet_currency_symbol


def get_wallet_reward_prize_name(user, amount=None):
    amount, currency_code, currency_symbol = get_wallet_reward_display(user, amount)
    return f"{currency_symbol}{amount:.2f} {currency_code} Wallet Reward"


def iter_earned_milestones(milestone, achieved_value):
    threshold = milestone['threshold']
    repeat_interval = milestone.get('repeat_interval')

    if achieved_value < threshold:
        return

    if not repeat_interval:
        yield threshold
        return

    current_threshold = threshold
    while current_threshold <= achieved_value:
        yield current_threshold
        current_threshold += repeat_interval


def credit_wallet_reward(user, achievement, amount=None):
    amount, currency_code, currency_symbol = get_wallet_reward_display(user, amount)
    profile = UserProfile.objects.select_for_update().get(user=user)
    UserProfile.objects.filter(pk=profile.pk).update(wallet_balance=F('wallet_balance') + amount)
    profile.refresh_from_db(fields=['wallet_balance'])
    WalletTransaction.objects.create(
        profile=profile,
        transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
        amount=amount,
        currency_code=currency_code,
        currency_symbol=currency_symbol,
        description=(
            f"{achievement.get_milestone_type_display()} milestone reward "
            f"at {achievement.threshold}"
        ),
        balance_after=profile.wallet_balance,
    )
    return amount


def get_survey_milestone_progress(user):
    """Progress toward the next surveys_completed milestone, for the dashboard.

    Returns None when there is no active surveys_completed milestone, or the
    user is excluded from it (e.g. Nigeria, or no country set) - the caller
    should hide the progress card entirely in that case.
    """
    milestone = next(
        (m for m in get_milestone_config() if m['milestone_type'] == 'surveys_completed'),
        None,
    )
    if not milestone:
        return None

    user_country_code = get_user_country_code(user)
    if is_milestone_excluded_for_user(user_country_code, milestone):
        return None

    interval = milestone.get('repeat_interval') or milestone['threshold']
    completed_surveys = get_user_milestone_stats(user)['surveys_completed']
    into_cycle = completed_surveys % interval
    to_next = interval - into_cycle

    amount, currency_code, currency_symbol = get_wallet_reward_display(
        user, milestone.get('wallet_reward_amount')
    )

    return {
        'interval': interval,
        'reward_amount': amount,
        'currency_symbol': currency_symbol,
        'surveys_completed': completed_surveys,
        'surveys_into_cycle': into_cycle,
        'surveys_to_next_reward': to_next,
        'next_milestone': completed_surveys + to_next,
        'progress_pct': int((into_cycle / interval) * 100),
    }


def check_and_award_milestones(user):
    awarded = []
    stats = get_user_milestone_stats(user)
    user_country_code = get_user_country_code(user)

    for milestone in get_milestone_config():
        if is_milestone_excluded_for_user(user_country_code, milestone):
            continue

        milestone_type = milestone['milestone_type']
        achieved_value = stats.get(milestone_type, 0)
        reward_amount = milestone.get('wallet_reward_amount')

        for threshold in iter_earned_milestones(milestone, achieved_value):
            prize_name = milestone.get('prize_name', 'Milestone Prize')
            if milestone.get('wallet_reward'):
                prize_name = get_wallet_reward_prize_name(user, reward_amount)

            defaults = {
                'achieved_value': achieved_value,
                'prize_name': prize_name,
            }

            try:
                with transaction.atomic():
                    achievement, created = MilestoneAchievement.objects.get_or_create(
                        user=user,
                        milestone_type=milestone_type,
                        threshold=threshold,
                        defaults=defaults,
                    )
                    if created and milestone.get('wallet_reward'):
                        credit_wallet_reward(user, achievement, reward_amount)
            except IntegrityError:
                continue

            if not created:
                if achievement.achieved_value < achieved_value:
                    achievement.achieved_value = achieved_value
                    achievement.save(update_fields=['achieved_value'])
                continue

            send_milestone_achievement_email(user, achievement)
            send_milestone_achievement_admin_notification(user, achievement)
            achievement.email_sent_at = timezone.now()
            achievement.save(update_fields=['email_sent_at'])
            awarded.append(achievement)

    return awarded
