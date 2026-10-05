"""Wipe survey, draw, wallet and milestone history so users start from zero.

    python manage.py reset_survey_progress                                  # dry run, everyone
    python manage.py reset_survey_progress --confirm                        # everyone (irreversible)
    python manage.py reset_survey_progress --country US --country GB        # dry run, only these countries
    python manage.py reset_survey_progress --country US --country GB --confirm

Clears: survey responses (and their answers), survey completion counts, every
Quick/Poll/Monthly draw entry (so Monthly eligibility is empty too), Monthly
winning numbers and settlements, all milestone achievements, all wallet
transactions and withdrawal requests, and sets wallet balances to 0.
With --country, only users whose profile is in those countries (and those
countries' winning numbers and settlements) are touched; UK is accepted for GB.
Keeps: users and profiles, surveys/categories/questions, polls and poll responses.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from surveys.models import (
    Answer, Country, LuckyDrawEntry, MilestoneAchievement, MonthlyDrawNumbers, MonthlyDrawSettlement,
    SurveyResponse, UserProfile, UserSurveyProgress, WalletTransaction, WalletWithdrawalRequest,
)

CODE_ALIASES = {'UK': 'GB', 'USA': 'US'}
User = get_user_model()


class Command(BaseCommand):
    help = "Reset users' surveys, draws, milestones and wallets to zero (dry run unless --confirm)."

    def add_arguments(self, parser):
        parser.add_argument('--country', action='append',
                            help='Country code (repeat for several). Default: every user.')
        parser.add_argument('--confirm', action='store_true', help='Actually delete the data.')

    def handle(self, *args, **options):
        countries = None
        if options['country']:
            codes = sorted({CODE_ALIASES.get(code.strip().upper(), code.strip().upper()) for code in options['country']})
            countries = list(Country.objects.filter(code__in=codes))
            missing = set(codes) - {str(c.code).upper() for c in countries}
            if missing:
                raise CommandError(f'No country with code {", ".join(sorted(missing))}. Nothing was changed.')
            self.stdout.write('Only users in: ' + ', '.join(f'{c.name} ({c.code})' for c in countries))
        else:
            self.stdout.write('All users, every country.')

        # Admin and staff accounts are never touched (superusers, staff, or profile type admin/staff).
        admin_user_ids = list(
            User.objects.filter(
                Q(is_superuser=True) | Q(is_staff=True) | Q(profile__user_type__in=('admin', 'staff'))
            ).values_list('id', flat=True)
        )
        self.stdout.write(f'Admin/staff accounts skipped: {len(admin_user_ids)}')
        def users(qs, user_field):
            """Rows belonging to non-admin users, in the chosen countries if any."""
            if countries is not None:
                qs = qs.filter(**{f'{user_field}__profile__country__in': countries})
            return qs.exclude(**{f'{user_field}__in': admin_user_ids})

        def by_country(qs):
            return qs.filter(country__in=countries) if countries is not None else qs

        deletions = [
            ('Survey responses', users(SurveyResponse.objects.all(), 'user')),
            ('  their answers', users(Answer.objects.all(), 'response__user')),
            ('Draw entries (Quick, Poll, Monthly)', users(LuckyDrawEntry.objects.all(), 'user')),
            ('Monthly draw winning numbers', by_country(MonthlyDrawNumbers.objects.all())),
            ('Monthly draw settlements', by_country(MonthlyDrawSettlement.objects.all())),
            ('Milestone achievements (all types)', users(MilestoneAchievement.objects.all(), 'user')),
            ('Withdrawal requests (all statuses)', users(WalletWithdrawalRequest.objects.all(), 'profile__user')),
            ('Wallet transactions', users(WalletTransaction.objects.all(), 'profile__user')),
        ]
        progress = users(UserSurveyProgress.objects.all(), 'user')
        profiles = users(UserProfile.objects.all(), 'user')

        self.stdout.write('Will delete:')
        for label, qs in deletions:
            self.stdout.write(f'  {label:40} {qs.count():>8}')
        self.stdout.write('Will set to 0:')
        self.stdout.write(f'  {"Survey completion counts (rows)":40} {progress.exclude(completed_count=0).count():>8}')
        self.stdout.write(f'  {"Wallet balances (non-zero)":40} {profiles.exclude(wallet_balance=0).count():>8}')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('\nDry run only. Re-run with --confirm to delete.'))
            return

        with transaction.atomic():
            for _label, qs in deletions:
                qs.delete()
            counts = progress.update(completed_count=0)
            balances = profiles.update(wallet_balance=Decimal('0.00'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {counts} survey completion rows and {balances} wallets set to 0; responses, '
            'draw entries, milestones, wallet transactions and withdrawal requests deleted.'
        ))
