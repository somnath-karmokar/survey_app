from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from surveys.milestones import check_and_award_milestones
from surveys.models import Country, MilestoneAchievement, Survey, SurveyCategory, SurveyResponse


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    ADMIN_EMAIL='admin@sudraw.com',
    MILESTONE_REWARDS=(
        {
            'milestone_type': 'surveys_completed',
            'threshold': 200,
            'prize_name': '200 Surveys Achievement Prize',
        },
        {
            'milestone_type': 'points_earned',
            'threshold': 2200,
            'prize_name': '2200 Points Achievement Prize',
        },
    ),
)
class MilestoneAchievementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='milestone@example.com',
            email='milestone@example.com',
            password='secret123',
            first_name='Mila',
        )
        self.country = Country.objects.create(name='United States', code='US')
        self.category = SurveyCategory.objects.create(
            name='General',
            country=self.country,
        )
        self.survey = Survey.objects.create(
            name='Reward Survey',
            category=self.category,
            is_active=True,
        )

    def _create_completed_surveys(self, count):
        responses = [
            SurveyResponse(
                user=self.user,
                survey=self.survey,
                completed_at=timezone.now(),
            )
            for _ in range(count)
        ]
        SurveyResponse.objects.bulk_create(responses)

    def test_awards_200_surveys_milestone_once(self):
        self._create_completed_surveys(200)

        awarded = check_and_award_milestones(self.user)

        self.assertEqual(len(awarded), 1)
        achievement = awarded[0]
        self.assertEqual(achievement.milestone_type, 'surveys_completed')
        self.assertEqual(achievement.threshold, 200)
        self.assertEqual(achievement.achieved_value, 200)
        self.assertEqual(MilestoneAchievement.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(mail.outbox[1].to, ['admin@sudraw.com'])

        awarded_again = check_and_award_milestones(self.user)
        self.assertEqual(awarded_again, [])
        self.assertEqual(MilestoneAchievement.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_awards_2200_points_milestone_once(self):
        self._create_completed_surveys(220)

        awarded = check_and_award_milestones(self.user)

        self.assertEqual(len(awarded), 2)
        self.assertTrue(
            MilestoneAchievement.objects.filter(
                milestone_type='surveys_completed',
                threshold=200,
            ).exists()
        )
        points_achievement = MilestoneAchievement.objects.get(
            milestone_type='points_earned',
            threshold=2200,
        )
        self.assertEqual(points_achievement.achieved_value, 2200)
        self.assertEqual(len(mail.outbox), 4)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(mail.outbox[1].to, ['admin@sudraw.com'])
        self.assertEqual(mail.outbox[2].to, [self.user.email])
        self.assertEqual(mail.outbox[3].to, ['admin@sudraw.com'])

        awarded_again = check_and_award_milestones(self.user)
        self.assertEqual(awarded_again, [])
        self.assertEqual(MilestoneAchievement.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 4)
