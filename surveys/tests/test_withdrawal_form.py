"""Withdrawal request page: each field only accepts the kind of value it should.

Names are letters, account numbers / sort codes / routing numbers are digits,
and the IBAN is letters and numbers. Everything is posted through the real page,
so this covers the errors a user actually sees and that nothing bad is saved.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from surveys.models import Country, WalletWithdrawalRequest

BASE = {
    'full_name': "Anne-Marie O'Brien",
    'email': 'anne@example.com',
    'amount': '10.00',
    'payment_method': 'bank_transfer',
    'bank_account_name': "Anne-Marie O'Brien",
}

# One known-good set of bank details per supported country.
BANK_FIELDS = {
    'GB': {'bank_account_number': '12345678', 'sort_code': '123456'},
    'US': {'bank_account_number': '123456789012', 'routing_number': '021000021'},
    'NG': {'bank_name': 'First Bank', 'nuban_number': '0123456789'},
    'CA': {'bank_account_number': '1234567', 'transit_number': '12345', 'institution_number': '004'},
}

# Not integers, even though some of these are "digits" as far as Python's
# str.isdigit() is concerned (superscripts, Arabic-Indic numerals).
NOT_INTEGERS = ['abc12345', '1234.5678', '+12345678', '1234567é', '12345678²', '١٢٣٤٥٦٧٨']


class WithdrawalFieldTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        names = {'GB': 'United Kingdom', 'US': 'United States', 'NG': 'Nigeria', 'CA': 'Canada'}
        cls.countries = {code: Country.objects.create(name=name, code=code) for code, name in names.items()}
        cls.user = get_user_model().objects.create_user(
            username='wd@example.com', email='wd@example.com', password='pw',
        )
        profile = cls.user.profile
        profile.country = cls.countries['GB']
        profile.wallet_balance = Decimal('100.00')
        profile.save()

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('surveys:wallet_withdrawal_request')

    # -- helpers ---------------------------------------------------------------

    def post(self, country='GB', **overrides):
        # Start from a clean slate so "was anything saved?" is answered per post.
        WalletWithdrawalRequest.objects.all().delete()
        data = {**BASE, 'country': self.countries[country].pk, **BANK_FIELDS[country], **overrides}
        return self.client.post(self.url, data)

    def assertAccepted(self, response):
        self.assertRedirects(response, reverse('surveys:wallet_history'), fetch_redirect_response=False)
        self.assertEqual(WalletWithdrawalRequest.objects.count(), 1)

    def assertRejected(self, response, field, message_fragment):
        """The page re-renders showing `field`'s error, and nothing was saved."""
        self.assertEqual(response.status_code, 200)
        errors = response.context['form'].errors
        self.assertIn(field, errors)
        self.assertTrue(
            any(message_fragment in message for message in errors[field]),
            f'{field}: expected "{message_fragment}" in {errors[field]}',
        )
        self.assertContains(response, message_fragment)
        self.assertEqual(WalletWithdrawalRequest.objects.count(), 0)

    # -- valid input -----------------------------------------------------------

    def test_valid_details_are_accepted_for_every_country(self):
        for code in BANK_FIELDS:
            with self.subTest(country=code):
                self.assertAccepted(self.post(code))

    def test_separators_are_stripped_and_iban_is_normalised(self):
        self.assertAccepted(self.post(
            bank_account_number='1234 5678',
            sort_code='12-34-56',
            iban='gb82 west 1234 5698 7654 32',
        ))
        saved = WalletWithdrawalRequest.objects.get()
        self.assertEqual(saved.bank_account_number, '12345678')
        self.assertEqual(saved.sort_code, '123456')
        self.assertEqual(saved.iban, 'GB82WEST12345698765432')

    def test_leading_zeros_survive(self):
        self.assertAccepted(self.post(bank_account_number='00012345', sort_code='00-12-34'))
        saved = WalletWithdrawalRequest.objects.get()
        self.assertEqual(saved.bank_account_number, '00012345')
        self.assertEqual(saved.sort_code, '001234')

    def test_full_name_is_prefilled_from_the_real_name_only(self):
        # Prefilling the username would hand users a value the letters-only rule rejects.
        response = self.client.get(self.url)
        self.assertIsNone(response.context['form']['full_name'].value() or None)

        self.user.first_name, self.user.last_name = 'Anne', "O'Brien"
        self.user.save()
        response = self.client.get(self.url)
        self.assertEqual(response.context['form']['full_name'].value(), "Anne O'Brien")

    # -- names: letters only ---------------------------------------------------

    def test_names_accept_real_world_names(self):
        for name in ["O'Brien", 'Anne-Marie', 'J. Smith', 'José García', 'Zoë', 'Siobhán Ní Bhriain', 'D’Angelo']:
            with self.subTest(name=name):
                self.assertAccepted(self.post(full_name=name, bank_account_name=name))

    def test_names_reject_digits_and_symbols(self):
        for field in ('full_name', 'bank_account_name'):
            for value in ['12345', 'John3', 'Anne_Marie', 'Anne@Marie', 'Anne²', '٣٤٥', '-Anne', '<b>Anne</b>']:
                with self.subTest(field=field, value=value):
                    self.assertRejected(self.post(**{field: value}), field, 'may only contain letters')

    # -- account identifiers: integers only ------------------------------------

    def test_account_number_is_digits_only(self):
        for value in NOT_INTEGERS:
            with self.subTest(value=value):
                self.assertRejected(self.post(bank_account_number=value), 'bank_account_number', 'only contain numbers')

    def test_sort_code_is_six_digits(self):
        for value in NOT_INTEGERS + ['12-34-5a', '١٢٣٤٥٦']:
            with self.subTest(value=value):
                self.assertRejected(self.post(sort_code=value), 'sort_code', 'Sort code')
        for value in ['12345', '1234567']:
            with self.subTest(value=value):
                self.assertRejected(self.post(sort_code=value), 'sort_code', 'exactly 6 digits')

    def test_other_countries_identifiers_are_digits_of_the_right_length(self):
        cases = [
            ('US', 'routing_number', ['12345678a', '12345678', '0210000210'], 'exactly 9 digits'),
            ('NG', 'nuban_number', ['012345678a', '012345678', '01234567890'], 'exactly 10 digits'),
            ('CA', 'transit_number', ['1234a', '1234', '123456'], 'exactly 5 digits'),
            ('CA', 'institution_number', ['00a', '0000', '04'], 'exactly 3 digits'),
        ]
        for country, field, values, length_message in cases:
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.post(country, **{field: value})
                    # letters/symbols get the "numbers" message, wrong lengths the length one
                    message = 'only contain numbers' if any(c.isalpha() for c in value) else length_message
                    self.assertRejected(response, field, message)

    # -- IBAN: letters and numbers ---------------------------------------------

    def test_iban_is_letters_and_numbers_only(self):
        for value in ['GB82 WEST!234 5698 7654 32', 'GB82WEST1234569876543é', 'GB82WEST1234569876543²', 'GB82_WEST12345698765432']:
            with self.subTest(value=value):
                self.assertRejected(self.post(iban=value), 'iban', 'only contain letters and numbers')

    def test_iban_must_look_like_an_iban(self):
        for value in ['GB82', '1234567890123456', 'GB82WEST12345698765432ABCDEFGHIJKLMNOP']:
            with self.subTest(value=value):
                self.assertRejected(self.post(iban=value), 'iban', 'IBAN must')
