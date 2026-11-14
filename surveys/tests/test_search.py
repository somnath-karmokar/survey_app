"""Site search (header search box): pages, no duplicates, grouped question matches."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import Country, Poll, PollQuestion, Question, Survey, SurveyCategory, UserProfile


def make_category(country, name, description=''):
    category = SurveyCategory.objects.create(name=name, country=country, description=description)
    survey = Survey.objects.create(name=name, category=category)
    return category, survey


class SearchTests(TestCase):
    def setUp(self):
        self.uk = Country.objects.create(name='United Kingdom', code='GB')
        self.ng = Country.objects.create(name='Nigeria', code='NG')
        self.cinema_uk, self.cinema_survey = make_category(self.uk, 'Cinema', 'Cinemas and movie theatres.')
        make_category(self.ng, 'Cinema', 'Cinemas and movie theatres.')
        self.cruise, self.cruise_survey = make_category(self.uk, 'Cruise Lines')
        for n, (topic, text) in enumerate([
            ('Embarkation Terminal Security', 'How long did boarding take at the cruise terminal?'),
            ('Cabin Cleanliness', 'How clean was your cabin on day one of the cruise?'),
            ('Dining', 'How was the food?'),
        ]):
            q = Question.objects.create(topic=topic, question_text=text, question_type='single_choice', order=n)
            q.surveys.add(self.cruise_survey)
        self.ng_only, _ = make_category(self.ng, 'Okada Rides')
        self.user = get_user_model().objects.create_user('s@example.com', 's@example.com', 'pw')
        self.client.force_login(self.user)
        UserProfile.objects.filter(user=self.user).update(country=self.uk)

    def search(self, q, client=None):
        return (client or self.client).get(reverse('surveys:search'), {'q': q})

    def results(self, q, client=None):
        return self.search(q, client).context['results']

    def test_visitors_see_each_category_once(self):
        self.client.logout()
        results = self.results('cinema')
        self.assertEqual([r['title'] for r in results if r['type'] == 'Category'], ['Cinema'])
        self.assertContains(self.search('cinema'), 'Login to search more')

    def test_site_pages_are_found_by_what_people_type(self):
        self.client.logout()
        for q, page in (('charity', 'Withdraw'), ('donate to charity', 'Withdraw'), ('paypal', 'Withdraw'),
                        ('lucky draw', 'Lucky Draw'), ('draw winners', 'Lucky Draw'), ('faq', 'FAQ'),
                        ('privacy', 'Privacy Policy'), ('contact', 'Contact Us')):
            titles = [r['title'] for r in self.results(q) if r['type'] == 'Page']
            self.assertIn(page, titles, q)

    def test_common_words_alone_find_nothing(self):
        self.assertEqual(self.results('the'), [])
        self.assertEqual(self.results('how to'), [])
        self.assertContains(self.search('a'), 'Please enter at least 2 characters')

    def test_logged_in_users_only_see_their_country(self):
        self.assertEqual(self.results('okada'), [])
        cinema = [r for r in self.results('cinema') if r['type'] == 'Category']
        self.assertEqual(len(cinema), 1)
        self.assertEqual(cinema[0]['url'], reverse('surveys:category_detail', args=[self.cinema_uk.slug]))

    def test_question_matches_are_one_result_per_survey(self):
        results = self.results('cabin')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Cruise Lines survey')
        self.assertEqual(results[0]['description'], '1 question mentions "cabin"')
        self.assertEqual(results[0]['url'], reverse('surveys:category_detail', args=[self.cruise.slug]))

    def test_category_and_its_questions_are_not_shown_twice(self):
        results = self.results('cruise')
        self.assertEqual([(r['type'], r['title']) for r in results], [('Category', 'Cruise Lines')])
        self.assertEqual(results[0]['description'], '2 questions mention "cruise"')

    def test_every_word_can_match_in_different_order(self):
        self.assertEqual([r['title'] for r in self.results('terminal embarkation')], ['Cruise Lines survey'])
        self.assertEqual([r['title'] for r in self.results('Embarkation Terminal')], ['Cruise Lines survey'])
        self.assertEqual(self.results('embarkation pizza'), [])

    def test_poll_questions_are_grouped_by_poll(self):
        poll = Poll.objects.create(title='Weekend plans', country=self.uk, is_active=True)
        for n in range(3):
            PollQuestion.objects.create(poll=poll, question_text=f'Will you visit a cinema {n}?',
                                        question_type='single_choice', order=n)
        polls = [r for r in self.results('cinema') if r['type'] == 'Poll']
        self.assertEqual([(r['title'], r['description']) for r in polls],
                         [('Weekend plans', '3 questions mention "cinema"')])

    def test_results_page_renders(self):
        page = self.search('cruise')
        self.assertContains(page, 'Cruise Lines')
        self.assertContains(page, '1 result')
