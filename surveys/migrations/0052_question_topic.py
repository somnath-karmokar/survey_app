from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0051_question_section_title'),
    ]

    operations = [
        migrations.AddField(
            model_name='question',
            name='topic',
            field=models.CharField(blank=True, help_text='Short heading shown above the question, e.g. "Embarkation Terminal Security and Boarding Throughput Velocity" (the "Q01." line in the survey document).', max_length=255, null=True, verbose_name='Topic'),
        ),
    ]
