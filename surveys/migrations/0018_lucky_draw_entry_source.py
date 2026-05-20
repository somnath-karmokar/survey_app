# Generated manually because Django is not installed in the active shell environment.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('surveys', '0017_country_lucky_draw_config_and_poll_counts'),
    ]

    operations = [
        migrations.AddField(
            model_name='luckydrawentry',
            name='draw_type',
            field=models.CharField(
                choices=[('survey', 'Survey'), ('poll', 'Poll')],
                db_index=True,
                default='survey',
                help_text='Whether this lucky draw play was earned from surveys or polls.',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='luckydrawentry',
            name='poll',
            field=models.ForeignKey(
                blank=True,
                help_text='Poll that qualified this lucky draw play, when applicable.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='lucky_draw_entries',
                to='surveys.poll',
            ),
        ),
        migrations.AddField(
            model_name='luckydrawentry',
            name='survey',
            field=models.ForeignKey(
                blank=True,
                help_text='Survey that qualified this lucky draw play, when applicable.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='lucky_draw_entries',
                to='surveys.survey',
            ),
        ),
    ]
