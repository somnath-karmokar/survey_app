"""Clear one country's Monthly draw for one month, so it can be played again (for testing).

    python manage.py reset_monthly_draw --country US                       # dry run, this month
    python manage.py reset_monthly_draw --country US --month 2026-10 --confirm
    python manage.py reset_monthly_draw --country US --reverse-wallet-credits --confirm

Deletes that month's Monthly draw plays (wins and losses, which gives players
their attempts back), the month's winning numbers and its settlement records.
Months follow the country's own clock. Wallets are left alone unless
--reverse-wallet-credits is given: then each Monthly prize credited for those
plays is taken back with a matching debit transaction.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from surveys.lucky_draw import month_bounds
from surveys.models import (
    CountryLuckyDrawConfig, LuckyDrawEntry, MonthlyDrawNumbers, MonthlyDrawSettlement, UserProfile,
    WalletTransaction,
)


class Command(BaseCommand):
    help = "Clear one country's Monthly draw plays, winning numbers and settlements for a month (dry run unless --confirm)."

    def add_arguments(self, parser):
        parser.add_argument('--country', required=True, help='Country code, e.g. US.')
        parser.add_argument('--month', help='YYYY-MM on the country\'s clock. Default: this month.')
        parser.add_argument('--reverse-wallet-credits', action='store_true',
                            help='Also take back the Monthly prizes these plays credited.')
        parser.add_argument('--confirm', action='store_true', help='Actually delete.')

    def handle(self, *args, **options):
        config = CountryLuckyDrawConfig.objects.filter(
            country__code__iexact=options['country'],
        ).select_related('country').first()
        if not config:
            raise CommandError(f"No lucky draw config for country {options['country']}.")

        _now, month_start, next_month_start = month_bounds(config.tzinfo)
        if options['month']:
            try:
                year, month = (int(part) for part in options['month'].split('-'))
                month_start = month_start.replace(year=year, month=month)
            except ValueError:
                raise CommandError('--month must look like 2026-10.')
            if month == 12:
                next_month_start = month_start.replace(year=year + 1, month=1)
            else:
                next_month_start = month_start.replace(month=month + 1)

        country = config.country
        entries = LuckyDrawEntry.objects.filter(
            draw_type=LuckyDrawEntry.DRAW_TYPE_MONTHLY,
            user__profile__country=country,
            created_at__gte=month_start,
            created_at__lt=next_month_start,
        ).select_related('user')
        numbers = MonthlyDrawNumbers.objects.filter(country=country, year=month_start.year, month=month_start.month)
        settlements = MonthlyDrawSettlement.objects.filter(
            country=country,
            draw_date__gte=month_start.date(),
            draw_date__lt=date(next_month_start.year, next_month_start.month, 1),
        )
        credits = WalletTransaction.objects.filter(
            lucky_draw_entry__in=entries, transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
        ).select_related('profile__user')

        self.stdout.write(f'{country.name} ({country.code}), {month_start:%B %Y} ({config.time_zone}):')
        self.stdout.write(f'  Monthly plays to delete:   {entries.count()} '
                          f'({entries.filter(is_winner=True).count()} wins)')
        for entry in entries:
            self.stdout.write(f'    {entry.created_at:%Y-%m-%d %H:%M} {entry.user.email:40} '
                              f'number {entry.guessed_number} {"WIN " + (entry.prize or "") if entry.is_winner else "lose"}')
        self.stdout.write(f'  Winning numbers to delete: {", ".join(str(n.winning_numbers) for n in numbers) or "none"}')
        self.stdout.write(f'  Settlements to delete:     {settlements.count()}')
        if options['reverse_wallet_credits']:
            self.stdout.write(f'  Wallet credits to reverse: {credits.count()}')
            for txn in credits:
                self.stdout.write(f'    {txn.profile.user.email:40} -{txn.currency_symbol}{txn.amount}')
        else:
            self.stdout.write(f'  Wallet credits kept:       {credits.count()} (add --reverse-wallet-credits to take them back)')

        if not options['confirm']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --confirm to delete.'))
            return

        with transaction.atomic():
            if options['reverse_wallet_credits']:
                for txn in credits:
                    profile = UserProfile.objects.select_for_update().get(pk=txn.profile_id)
                    UserProfile.objects.filter(pk=profile.pk).update(wallet_balance=F('wallet_balance') - txn.amount)
                    profile.refresh_from_db(fields=['wallet_balance'])
                    WalletTransaction.objects.create(
                        profile=profile,
                        transaction_type=WalletTransaction.TRANSACTION_TYPE_DEBIT,
                        amount=txn.amount,
                        currency_code=txn.currency_code,
                        currency_symbol=txn.currency_symbol,
                        description=f'Reversed: {txn.description} (Monthly draw reset for testing)',
                        balance_after=profile.wallet_balance,
                    )
            deleted_entries = entries.count()
            entries.delete()
            numbers.delete()
            settlements.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Done. {deleted_entries} Monthly play(s), the winning numbers and settlements for '
            f'{country.code} {month_start:%B %Y} are cleared.'
        ))
