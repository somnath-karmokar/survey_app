"""Configure the monthly lucky draw: 4 winners/month per country, at
$10 USD/GBP for UK, USA and Canada, and $5 USD for Nigeria.

Updates the existing CountryLuckyDrawConfig row for each country (created if
a country is missing one); leaves every other country's config untouched.
"""
from decimal import Decimal

from django.db import migrations


PRIZES = {
    'GB': {'prize_amount': Decimal('10.00'), 'currency_code': 'GBP', 'currency_symbol': '£'},
    'US': {'prize_amount': Decimal('10.00'), 'currency_code': 'USD', 'currency_symbol': '$'},
    'CA': {'prize_amount': Decimal('10.00'), 'currency_code': 'USD', 'currency_symbol': '$'},
    'NG': {'prize_amount': Decimal('5.00'), 'currency_code': 'USD', 'currency_symbol': '$'},
}
MONTHLY_WINNER_CAP = 4


def seed_prizes(apps, schema_editor):
    Country = apps.get_model('surveys', 'Country')
    CountryLuckyDrawConfig = apps.get_model('surveys', 'CountryLuckyDrawConfig')

    for code, prize in PRIZES.items():
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        CountryLuckyDrawConfig.objects.update_or_create(
            country=country,
            defaults={
                **prize,
                'monthly_winner_cap': MONTHLY_WINNER_CAP,
                'is_active': True,
            },
        )


def noop_reverse(apps, schema_editor):
    # Data seed only - no schema to reverse. Re-running the previous
    # migration state does not need these rows removed.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0035_add_monthly_winner_cap'),
    ]

    operations = [
        migrations.RunPython(seed_prizes, noop_reverse),
    ]
