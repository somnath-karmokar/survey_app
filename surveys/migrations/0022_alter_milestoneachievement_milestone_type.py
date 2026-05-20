# Generated manually because Django is not installed in the active shell environment.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0021_userwallet'),
    ]

    operations = [
        migrations.AlterField(
            model_name='milestoneachievement',
            name='milestone_type',
            field=models.CharField(
                choices=[
                    ('surveys_completed', 'Surveys Completed'),
                    ('polls_completed', 'Polls Completed'),
                    ('points_earned', 'Points Earned'),
                ],
                max_length=32,
            ),
        ),
    ]
