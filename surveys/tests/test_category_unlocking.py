from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from surveys.models import Country, Survey, SurveyCategory, SurveyResponse


@override_settings(SURVEY_CONFIG={'DEFAULT_COOLDOWN_DAYS': 10})
class CategoryUnlockingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='levels@example.com',
            email='levels@example.com',
            password='secret123',
        )
        self.client.force_login(self.user)

        self.country = Country.objects.create(name='India', code='IN')
        self.category = SurveyCategory.objects.create(
            name='Health',
            slug='health',
            country=self.country,
        )

        self.level1_a = Survey.objects.create(
            name='Level 1A',
            category=self.category,
            level=1,
            is_active=True,
        )
        self.level1_b = Survey.objects.create(
            name='Level 1B',
            category=self.category,
            level=1,
            is_active=True,
        )
        self.level2 = Survey.objects.create(
            name='Level 2',
            category=self.category,
            level=2,
            is_active=True,
        )

    def _complete(self, survey, *, days_ago=0):
        SurveyResponse.objects.create(
            user=self.user,
            survey=survey,
            completed_at=timezone.now() - timedelta(days=days_ago),
        )

    def test_next_survey_stays_locked_until_previous_survey_is_completed_in_sequence(self):
        self._complete(self.level1_a)

        response = self.client.get(
            reverse('surveys:category_detail', kwargs={'category_slug': self.category.slug})
        )

        surveys = response.context['surveys']
        self.assertEqual([entry['survey'].id for entry in surveys], [
            self.level1_a.id,
            self.level1_b.id,
            self.level2.id,
        ])

        level1_b_entry = next(entry for entry in surveys if entry['survey'].id == self.level1_b.id)
        self.assertFalse(level1_b_entry['is_locked'])

        level2_entry = next(entry for entry in surveys if entry['survey'].id == self.level2.id)
        self.assertTrue(level2_entry['is_locked'])
        self.assertEqual(level2_entry['lock_message'], "Complete 'Level 1B' (Level 1) to unlock")

        self._complete(self.level1_b)

        response = self.client.get(
            reverse('surveys:category_detail', kwargs={'category_slug': self.category.slug})
        )
        surveys = response.context['surveys']
        level2_entry = next(entry for entry in surveys if entry['survey'].id == self.level2.id)
        self.assertFalse(level2_entry['is_locked'])

    def test_ready_to_retake_is_suppressed_when_previous_level_is_incomplete(self):
        self._complete(self.level1_a, days_ago=20)
        self._complete(self.level2, days_ago=20)

        response = self.client.get(
            reverse('surveys:category_detail', kwargs={'category_slug': self.category.slug})
        )

        level2_entry = next(
            entry for entry in response.context['surveys']
            if entry['survey'].id == self.level2.id
        )
        self.assertTrue(level2_entry['is_completed'])
        self.assertTrue(level2_entry['is_locked'])
        self.assertFalse(level2_entry['can_retake'])
        self.assertEqual(level2_entry['lock_message'], "Retake 'Level 1A' (Level 1) first")

    def test_take_survey_blocks_direct_access_when_previous_level_is_incomplete(self):
        self._complete(self.level1_a)

        response = self.client.get(
            reverse('surveys:take_survey', kwargs={'survey_id': self.level2.id}),
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse('surveys:category_detail', kwargs={'category_slug': self.category.slug}),
        )
        messages = [message.message for message in response.context['messages']]
        self.assertIn("Complete 'Level 1B' (Level 1) to unlock", messages)

    def test_level_two_retake_requires_level_one_to_be_retaken_first(self):
        self._complete(self.level1_a, days_ago=40)
        self._complete(self.level1_b, days_ago=39)
        self._complete(self.level2, days_ago=38)

        response = self.client.get(
            reverse('surveys:take_survey', kwargs={'survey_id': self.level2.id}),
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse('surveys:category_detail', kwargs={'category_slug': self.category.slug}),
        )
        messages = [message.message for message in response.context['messages']]
        self.assertIn("Retake 'Level 1A' (Level 1) first", messages)

    def test_survey_detail_blocks_direct_access_when_previous_level_is_incomplete(self):
        self._complete(self.level1_a)

        response = self.client.get(
            reverse('surveys:survey_detail', kwargs={'survey_id': self.level2.id}),
            follow=True,
        )

        self.assertRedirects(
            response,
            reverse('surveys:category_detail', kwargs={'category_slug': self.category.slug}),
        )
        messages = [message.message for message in response.context['messages']]
        self.assertIn("Complete 'Level 1B' (Level 1) to unlock", messages)
