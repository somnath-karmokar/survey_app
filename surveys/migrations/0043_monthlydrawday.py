from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0042_monthlydrawsettlement'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyDrawDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('draw_date', models.DateField(unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-draw_date'],
            },
        ),
    ]
