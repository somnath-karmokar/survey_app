"""Give each country's lucky draw config its own time zone, so the Monthly draw
opens at local midnight on the 1st. Seeds sensible defaults for the countries
that take part; any other country stays on UTC until set in the admin.
"""
from django.db import migrations, models


DEFAULT_TIME_ZONES = {
    'GB': 'Europe/London',
    'NG': 'Africa/Lagos',
    'US': 'America/New_York',
    'CA': 'America/Toronto',
    'IN': 'Asia/Kolkata',
    'AU': 'Australia/Sydney',
}


def seed_time_zones(apps, schema_editor):
    CountryLuckyDrawConfig = apps.get_model('surveys', 'CountryLuckyDrawConfig')
    for config in CountryLuckyDrawConfig.objects.select_related('country'):
        time_zone = DEFAULT_TIME_ZONES.get(str(config.country.code or '').upper())
        if time_zone:
            config.time_zone = time_zone
            config.save(update_fields=['time_zone'])


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0039_monthlydraweligibleuser'),
    ]

    operations = [
        migrations.AddField(
            model_name='countryluckydrawconfig',
            name='time_zone',
            field=models.CharField(
                default='UTC', max_length=64,
                help_text='IANA time zone, e.g. Europe/London, Africa/Lagos, America/New_York. The Monthly draw '
                          'opens at 00:00 on the 1st and each month starts at midnight in this time zone.',
            ),
        ),
        migrations.RunPython(seed_time_zones, migrations.RunPython.noop),
    ]
