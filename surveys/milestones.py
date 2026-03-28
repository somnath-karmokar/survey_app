from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .emails import (
    send_milestone_achievement_admin_notification,
    send_milestone_achievement_email,
)
from .models import MilestoneAchievement, SurveyResponse


DEFAULT_MILESTONE_CONFIG = (
    {
        'milestone_type': 'surveys_completed',
        'threshold': 200,
        'prize_name': 'Milestone Prize',
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
    points_earned = completed_surveys * 10
    return {
        'surveys_completed': completed_surveys,
        'points_earned': points_earned,
    }


def get_milestone_config():
    return getattr(settings, 'MILESTONE_REWARDS', DEFAULT_MILESTONE_CONFIG)


def check_and_award_milestones(user):
    awarded = []
    stats = get_user_milestone_stats(user)

    for milestone in get_milestone_config():
        milestone_type = milestone['milestone_type']
        threshold = milestone['threshold']
        achieved_value = stats.get(milestone_type, 0)

        if achieved_value < threshold:
            continue

        defaults = {
            'achieved_value': achieved_value,
            'prize_name': milestone.get('prize_name', 'Milestone Prize'),
        }

        try:
            with transaction.atomic():
                achievement, created = MilestoneAchievement.objects.get_or_create(
                    user=user,
                    milestone_type=milestone_type,
                    threshold=threshold,
                    defaults=defaults,
                )
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
