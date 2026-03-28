from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AccountDeletionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username='delete-me',
            email='delete@example.com',
            password='secret123',
        )
        self.client.login(username='delete-me', password='secret123')

    def test_delete_account_requires_post(self):
        response = self.client.get(reverse('surveys:delete_account'))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_delete_account_removes_user_and_redirects_home(self):
        response = self.client.post(
            reverse('surveys:delete_account'),
            {'delete_confirmation': 'delete profile'},
            follow=True,
        )

        self.assertRedirects(response, reverse('surveys:home'))
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_delete_account_rejects_incorrect_confirmation_phrase(self):
        response = self.client.post(
            reverse('surveys:delete_account'),
            {'delete_confirmation': 'delete'},
            follow=True,
        )

        self.assertRedirects(response, reverse('surveys:user_profile'))
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
