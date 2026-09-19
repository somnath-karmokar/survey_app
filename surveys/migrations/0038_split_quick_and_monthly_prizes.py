"""Separate the Quick draw from the Monthly draw.

Migration 0036 put the Monthly draw's prizes (10 / 5) and its 4-winner cap on
the *Quick* draw's config. The two are different draws, so this puts the Quick
draw back to its original prizes with no winner cap, and moves the Monthly
numbers onto the Monthly fields:

    Quick draw   US / CA: $1     GB: 1 GBP     NG: $0.50     (no winner cap)
    Monthly draw US / CA: $10    GB: 10 GBP    NG: $5        (4 winners a month per country)

Only these four countries take part in the Monthly draw. Other countries are
left untouched.
"""
from decimal import Decimal

from django.db import migrations


# code -> (quick prize, monthly prize)
PRIZES = {
    'US': (Decimal('1.00'), Decimal('10.00')),
    'CA': (Decimal('1.00'), Decimal('10.00')),
    'GB': (Decimal('1.00'), Decimal('10.00')),
    'NG': (Decimal('0.50'), Decimal('5.00')),
}
CURRENCY = {
    'US': ('USD', '$'),
    'CA': ('USD', '$'),
    'GB': ('GBP', '£'),
    'NG': ('USD', '$'),
}
MONTHLY_WINNERS_PER_COUNTRY = 4


def split_prizes(apps, schema_editor):
    Country = apps.get_model('surveys', 'Country')
    CountryLuckyDrawConfig = apps.get_model('surveys', 'CountryLuckyDrawConfig')

    for code, (quick_prize, monthly_prize) in PRIZES.items():
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        currency_code, currency_symbol = CURRENCY[code]
        CountryLuckyDrawConfig.objects.update_or_create(
            country=country,
            defaults={
                'prize_amount': quick_prize,
                'currency_code': currency_code,
                'currency_symbol': currency_symbol,
                'monthly_prize_amount': monthly_prize,
                'monthly_winner_cap': MONTHLY_WINNERS_PER_COUNTRY,
                'is_active': True,
            },
        )


def noop_reverse(apps, schema_editor):
    # Data only; the schema migration before this one owns the columns.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0037_monthly_draw'),
    ]

    operations = [
        migrations.RunPython(split_prizes, noop_reverse),
    ]
