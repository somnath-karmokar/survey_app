# Generated manually because Django is not installed in the active shell environment.

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


def seed_country_lucky_draw_configs(apps, schema_editor):
    Country = apps.get_model('surveys', 'Country')
    CountryLuckyDrawConfig = apps.get_model('surveys', 'CountryLuckyDrawConfig')

    defaults = {
        'US': {'prize_amount': Decimal('1.00'), 'currency_symbol': '$', 'currency_code': 'USD'},
        'CA': {'prize_amount': Decimal('1.00'), 'currency_symbol': '$', 'currency_code': 'USD'},
        'GB': {'prize_amount': Decimal('1.00'), 'currency_symbol': '£', 'currency_code': 'GBP'},
        'NG': {'prize_amount': Decimal('0.50'), 'currency_symbol': '$', 'currency_code': 'USD'},
    }

    for code, values in defaults.items():
        country = Country.objects.filter(code=code).first()
        if country:
            CountryLuckyDrawConfig.objects.get_or_create(
                country=country,
                defaults={
                    'poll_count_required': 5,
                    **values,
                }
            )


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0016_pollquestion_more_types_pollanswer_rating'),
    ]

    operations = [
        migrations.CreateModel(
            name='CountryLuckyDrawConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('poll_count_required', models.PositiveIntegerField(default=5)),
                ('prize_amount', models.DecimalField(decimal_places=2, default=1, max_digits=8)),
                ('currency_symbol', models.CharField(default='$', max_length=5)),
                ('currency_code', models.CharField(default='USD', max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('country', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='lucky_draw_config', to='surveys.country')),
            ],
            options={
                'verbose_name': 'Country Lucky Draw Config',
                'verbose_name_plural': 'Country Lucky Draw Configs',
            },
        ),
        migrations.AddField(
            model_name='luckydrawentry',
            name='polls_at_play',
            field=models.PositiveIntegerField(default=0, help_text='Total polls completed when this entry was created'),
        ),
        migrations.RunPython(seed_country_lucky_draw_configs, migrations.RunPython.noop),
    ]
