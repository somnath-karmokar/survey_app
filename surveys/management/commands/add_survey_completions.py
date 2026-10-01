"""Record survey completions for one or more users, for testing the draws and milestones.

    python manage.py add_survey_completions --email a@x.com --email b@x.com --count 5            # dry run
    python manage.py add_survey_completions --email a@x.com --email b@x.com --count 5 --confirm  # write

Each completion is recorded the way a real one is: a completed SurveyResponse
(dated now), +1 on the matching UserSurveyProgress row, then the milestone check.
Surveys are taken from each user's country, cycling through them if needed.
Answers are not filled in. Every email is checked before anything is written.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from surveys.milestones import check_and_award_milestones
from surveys.models import Survey, SurveyResponse, UserSurveyProgress


class Command(BaseCommand):
    help = 'Record N survey completions for each given user (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--email', action='append', required=True, help='Repeat for several users.')
        parser.add_argument('--count', type=int, required=True, help='Completions to add per user.')
        parser.add_argument('--confirm', action='store_true', help='Actually write the completions.')

    def handle(self, *args, **options):
        count = options['count']
        if count < 1:
            raise CommandError('--count must be at least 1.')

        emails = list(dict.fromkeys(email.strip().lower() for email in options['email']))
        if len(emails) < len(options['email']):
            self.stdout.write(self.style.WARNING('Duplicate emails ignored.'))

        plans = []
        for email in emails:
            user = get_user_model().objects.filter(email__iexact=email).select_related('profile__country').first()
            if not user:
                raise CommandError(f'No user with email {email}. Nothing was written.')
            country = getattr(getattr(user, 'profile', None), 'country', None)
            if not country:
                raise CommandError(f'{user.email} has no country on their profile. Nothing was written.')
            surveys = list(
                Survey.objects.filter(is_active=True, category__country=country)
                .select_related('category').order_by('category__order', 'level', 'id')
            )
            if not surveys:
                raise CommandError(f'No active surveys for {country.name} ({user.email}). Nothing was written.')
            plans.append((user, country, [surveys[i % len(surveys)] for i in range(count)]))

        for user, country, picked in plans:
            self.stdout.write(f'{user.email} ({country.name}): {self.total(user)} completed now, +{count}.')
        countries = {country.code for _user, country, _picked in plans}
        if len(countries) > 1:
            self.stdout.write(self.style.WARNING(
                f'Users are in different countries ({", ".join(sorted(countries))}); '
                'the Monthly draw minimum counts each country separately.'
            ))

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to write.'))
            return

        for user, _country, picked in plans:
            with transaction.atomic():
                for survey in picked:
                    SurveyResponse.objects.create(user=user, survey=survey, completed_at=timezone.now())
                    progress, created = UserSurveyProgress.objects.get_or_create(
                        user=user, category=survey.category, level=survey.level, defaults={'completed_count': 1},
                    )
                    if not created:
                        UserSurveyProgress.objects.filter(pk=progress.pk).update(
                            completed_count=F('completed_count') + 1
                        )
            awarded = check_and_award_milestones(user)
            self.stdout.write(self.style.SUCCESS(
                f'{user.email}: now {self.total(user)} completed'
                + (f', {len(awarded)} milestone reward(s) awarded.' if awarded else '.')
            ))

    @staticmethod
    def total(user):
        return UserSurveyProgress.objects.filter(user=user).aggregate(t=Sum('completed_count'))['t'] or 0
