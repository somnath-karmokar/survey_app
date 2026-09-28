from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0038_split_quick_and_monthly_prizes'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyDrawEligibleUser',
            fields=[
            ],
            options={
                'verbose_name': 'Monthly Draw Eligible User',
                'verbose_name_plural': 'Monthly Draw Eligible Users',
                'ordering': ['user__username'],
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('surveys.userprofile',),
        ),
    ]
