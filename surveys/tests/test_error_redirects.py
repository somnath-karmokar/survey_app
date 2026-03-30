from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(ROOT_URLCONF='surveys.tests.test_error_redirects_urls')
class ErrorRedirectMiddlewareTests(TestCase):
    def test_unknown_page_redirects_to_home(self):
        response = self.client.get('/missing-page/', follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('surveys:home'))

    def test_unhandled_exception_redirects_to_home(self):
        response = self.client.get('/crash/', follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('surveys:home'))
