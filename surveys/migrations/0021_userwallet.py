# Generated manually because Django is not installed in the active shell environment.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0020_wallettransaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserWallet',
            fields=[
            ],
            options={
                'verbose_name': 'User Wallet Detail',
                'verbose_name_plural': 'User Wallet Details',
                'ordering': ['user__username'],
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('surveys.userprofile',),
        ),
    ]
