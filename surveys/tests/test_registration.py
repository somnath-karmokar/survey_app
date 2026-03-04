from django.test import TestCase, Client
from django.urls import reverse
from surveys.models import Country
from django.utils import timezone

class RegistrationTest(TestCase):
    def setUp(self):
        # create a dummy country for selection
        self.country = Country.objects.create(name='Testland')
        self.client = Client()
        self.signup_url = reverse('surveys:signup')

    def test_city_and_country_required(self):
        # submit form missing city and country
        data = {
            'email': 'user@example.com',
            'first_name': 'John',
            'last_name': 'Doe',
            # city omitted intentionally
            'state': 'SomeState',
            # country omitted intentionally
            'year_of_birth': '1990',
            'profile_picture': '',
        }
        response = self.client.post(self.signup_url, data)
        # form should be invalid and page re-rendered (status 200)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'signup_form', 'city', 'This field is required.')
        self.assertFormError(response, 'signup_form', 'country', 'This field is required.')

    def test_successful_submission_with_city_country(self):
        data = {
            'email': 'user2@example.com',
            'first_name': 'Jane',
            'last_name': 'Smith',
            'city': 'Metroville',
            'state': 'State',
            'country': str(self.country.id),
            'year_of_birth': '1990',
        }
        response = self.client.post(self.signup_url, data, follow=True)
        # on success should redirect or show appropriate message
        self.assertEqual(response.status_code, 200)
        # ensure user was created
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.assertTrue(User.objects.filter(email='user2@example.com').exists())


class AutoLogoutTest(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(username='temp', password='secret')
        self.client = Client()
        self.client.login(username='temp', password='secret')
        self.url = reverse('surveys:home') if 'home' in [u.name for u in self.client.get(reverse('surveys:login')).resolver_match.route] else '/'
        # note: above is placeholder, will just use root for now
        self.url = '/'

    def test_inactivity_logs_out(self):
        session = self.client.session
        old_time = (timezone.now() - timezone.timedelta(seconds=7201)).isoformat()
        session['last_activity'] = old_time
        session.save()

        response = self.client.get(self.url, follow=True)
        # after request user should be logged out
        self.assertFalse('_auth_user_id' in self.client.session)
