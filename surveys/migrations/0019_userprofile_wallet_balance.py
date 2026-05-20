# Generated manually because Django is not installed in the active shell environment.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0018_lucky_draw_entry_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='wallet_balance',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]
