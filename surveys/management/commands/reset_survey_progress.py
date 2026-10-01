"""Wipe survey, draw, wallet and milestone history so every user starts from zero.

    python manage.py reset_survey_progress            # dry run: shows what would go
    python manage.py reset_survey_progress --confirm  # actually deletes (irreversible)

Clears: survey responses (and their answers), survey completion counts, every
Quick/Poll/Monthly draw entry (so Monthly eligibility is empty too), all
milestone achievements, all wallet transactions and withdrawal requests, and
sets every wallet balance to 0.
Keeps: users and profiles, surveys/categories/questions, polls and poll responses.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from surveys.models import (
    Answer, LuckyDrawEntry, MilestoneAchievement, MonthlyDrawNumbers, MonthlyDrawSettlement, SurveyResponse, UserProfile, UserSurveyProgress,
    WalletTransaction, WalletWithdrawalRequest,
)


class Command(BaseCommand):
    help = 'Reset every user\'s surveys, draws, milestones and wallet to zero (dry run unless --confirm).'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Actually delete the data.')

    def handle(self, *args, **options):
        deletions = [
            ('Survey responses', SurveyResponse.objects.all()),
            ('  their answers', Answer.objects.all()),
            ('Draw entries (Quick, Poll, Monthly)', LuckyDrawEntry.objects.all()),
            ('Monthly draw winning numbers', MonthlyDrawNumbers.objects.all()),
            ('Monthly draw settlements', MonthlyDrawSettlement.objects.all()),
            ('Milestone achievements (all types)', MilestoneAchievement.objects.all()),
            ('Withdrawal requests (all statuses)', WalletWithdrawalRequest.objects.all()),
            ('Wallet transactions', WalletTransaction.objects.all()),
        ]
        progress = UserSurveyProgress.objects.exclude(completed_count=0)
        wallets = UserProfile.objects.exclude(wallet_balance=0)

        self.stdout.write('Will delete:')
        for label, qs in deletions:
            self.stdout.write(f'  {label:40} {qs.count():>8}')
        self.stdout.write('Will set to 0:')
        self.stdout.write(f'  {"Survey completion counts (rows)":40} {progress.count():>8}')
        self.stdout.write(f'  {"Wallet balances (non-zero)":40} {wallets.count():>8}')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('\nDry run only. Re-run with --confirm to delete.'))
            return

        with transaction.atomic():
            for _label, qs in deletions:
                qs.delete()
            counts = UserSurveyProgress.objects.update(completed_count=0)
            balances = UserProfile.objects.update(wallet_balance=Decimal('0.00'))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {counts} survey completion rows and {balances} wallets set to 0; responses, '
            'draw entries, milestones, wallet transactions and withdrawal requests deleted.'
        ))
