from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0001_initial'),  # Make sure this matches your last migration
    ]

    operations = [
        # Remove any existing country field if it exists
        migrations.RemoveField(
            model_name='userprofile',
            name='country',
        ),
        # Add the country field as a foreign key
        migrations.AddField(
            model_name='userprofile',
            name='country',
            field=models.ForeignKey(
                'surveys.Country',
                on_delete=django.db.models.deletion.SET_NULL,
                null=True,
                blank=True,
                db_column='country'  # Explicitly set the column name
            ),
        ),
    ]