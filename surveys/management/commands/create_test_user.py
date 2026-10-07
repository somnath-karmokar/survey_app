"""Create a ready-to-use test user (email already verified, country set).

    python manage.py create_test_user --email tester1@example.com --password 'Secret123!' --country GB
    python manage.py create_test_user --email tester1@example.com --password 'Secret123!' --country GB \\
        --first-name Test --last-name One --surveys 5

--surveys N also records N survey completions for the user (as add_survey_completions does),
so with MONTHLY_SURVEYS_REQUIRED = 5 they hold a Monthly draw attempt straight away.
Refuses to touch an email that already has an account.
"""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from surveys.models import Country

CODE_ALIASES = {'UK': 'GB', 'USA': 'US'}


class Command(BaseCommand):
    help = 'Create a verified test user in a given country, optionally with completed surveys.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--password', required=True)
        parser.add_argument('--country', required=True, help='Country code, e.g. GB, US, CA, NG.')
        parser.add_argument('--first-name', default='Test')
        parser.add_argument('--last-name', default='User')
        parser.add_argument('--city', default='Test City')
        parser.add_argument('--surveys', type=int, default=0, help='Survey completions to add.')

    def handle(self, *args, **options):
        User = get_user_model()
        email = options['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise CommandError(f'{email} already has an account. Nothing was changed.')

        code = options['country'].strip().upper()
        code = CODE_ALIASES.get(code, code)
        country = Country.objects.filter(code=code).first()
        if not country:
            raise CommandError(f'No country with code {code}. Nothing was changed.')

        with transaction.atomic():
            user = User.objects.create_user(
                username=email, email=email, password=options['password'],
                first_name=options['first_name'], last_name=options['last_name'],
            )
            profile = user.profile
            profile.country = country
            profile.city = options['city']
            profile.email_verified = True
            profile.user_type = 'frontend'
            profile.save(update_fields=['country', 'city', 'email_verified', 'user_type'])

        self.stdout.write(self.style.SUCCESS(
            f'Created {email} ({options["first_name"]} {options["last_name"]}, {country.name}). '
            'Log in with this email and the password you gave.'
        ))

        if options['surveys'] > 0:
            call_command('add_survey_completions', email=[email], count=options['surveys'], confirm=True,
                         stdout=self.stdout)
