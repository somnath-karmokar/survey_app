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
        'threshold': 200,
        'prize_name': 'Wallet Reward',
        'repeat_interval': 200,
        'wallet_reward': True,
    },
    {
        'milestone_type': 'polls_completed',
        'threshold': 200,
        'prize_name': 'Wallet Reward',
        'repeat_interval': 200,
        'wallet_reward': True,
    },
    {
        'milestone_type': 'points_earned',
        'threshold': 2200,
        'prize_name': 'Milestone Prize',
    },
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


def get_milestone_config():
    return getattr(settings, 'MILESTONE_REWARDS', DEFAULT_MILESTONE_CONFIG)


def get_wallet_reward_display(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return Decimal('1.00'), profile.wallet_currency_code, profile.wallet_currency_symbol


def get_wallet_reward_prize_name(user):
    amount, currency_code, currency_symbol = get_wallet_reward_display(user)
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


def credit_wallet_reward(user, achievement):
    amount, currency_code, currency_symbol = get_wallet_reward_display(user)
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


def check_and_award_milestones(user):
    awarded = []
    stats = get_user_milestone_stats(user)

    for milestone in get_milestone_config():
        milestone_type = milestone['milestone_type']
        achieved_value = stats.get(milestone_type, 0)

        for threshold in iter_earned_milestones(milestone, achieved_value):
            prize_name = milestone.get('prize_name', 'Milestone Prize')
            if milestone.get('wallet_reward'):
                prize_name = get_wallet_reward_prize_name(user)

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
                        credit_wallet_reward(user, achievement)
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
