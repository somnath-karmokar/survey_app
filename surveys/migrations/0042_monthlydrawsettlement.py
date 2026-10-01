from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0041_monthlydrawnumbers'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyDrawSettlement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('draw_date', models.DateField(help_text="The draw day (the 1st, or the test date) on the country's clock.")),
                ('qualifiers', models.PositiveIntegerField(default=0)),
                ('quorum_met', models.BooleanField(default=False)),
                ('paid_users', models.PositiveIntegerField(default=0)),
                ('settled_at', models.DateTimeField(auto_now_add=True)),
                ('country', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='monthly_draw_settlements', to='surveys.country',
                )),
            ],
            options={
                'ordering': ['-draw_date'],
                'unique_together': {('country', 'draw_date')},
            },
        ),
    ]
