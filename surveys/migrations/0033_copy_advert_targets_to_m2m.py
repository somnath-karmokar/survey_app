"""Carry each advert's single country/category across to the new
many-to-many fields before the old foreign keys are dropped.
"""
from django.db import migrations


def copy_to_m2m(apps, schema_editor):
    for model_name in ('Advertiser', 'DirectMarketing'):
        model = apps.get_model('surveys', model_name)
        for advert in model.objects.all():
            if advert.country_id:
                advert.countries.add(advert.country_id)
            if advert.category_id:
                advert.categories.add(advert.category_id)


def copy_back_to_fk(apps, schema_editor):
    """Reverse: keep the first of each set, which is all a single FK can hold."""
    for model_name in ('Advertiser', 'DirectMarketing'):
        model = apps.get_model('surveys', model_name)
        for advert in model.objects.all():
            first_country = advert.countries.first()
            first_category = advert.categories.first()
            advert.country_id = first_country.pk if first_country else None
            advert.category_id = first_category.pk if first_category else None
            advert.save(update_fields=['country', 'category'])


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0032_add_advert_m2m_targets'),
    ]

    operations = [
        migrations.RunPython(copy_to_m2m, copy_back_to_fk),
    ]
