from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0040_countryluckydrawconfig_time_zone'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyDrawNumbers',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveSmallIntegerField()),
                ('month', models.PositiveSmallIntegerField()),
                ('winning_numbers', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('country', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='monthly_draw_numbers', to='surveys.country',
                )),
            ],
            options={
                'verbose_name': 'Monthly Draw Numbers',
                'verbose_name_plural': 'Monthly Draw Numbers',
                'ordering': ['-year', '-month'],
                'unique_together': {('country', 'year', 'month')},
            },
        ),
    ]
