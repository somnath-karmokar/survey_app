# Generated manually because Django is not installed in the active shell environment.

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0015_poll_pollquestion_pollchoice_pollresponse_pollanswer'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pollquestion',
            name='question_type',
            field=models.CharField(
                choices=[
                    ('text', 'Text Answer'),
                    ('single_choice', 'Single Choice'),
                    ('multiple_choice', 'Multiple Choice'),
                    ('rating', 'Rating (1-5)'),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='pollanswer',
            name='rating_value',
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(5)],
            ),
        ),
    ]
