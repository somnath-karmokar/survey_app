"""Repair databases that ran an earlier draft of migration 0046.

That draft added Question.allow_not_listed (an on/off flag); the final 0046 adds
Question.not_listed_label (the wording of the screening question's type-your-own
box) instead. A database that already recorded the draft never gets the final
column, so this migration:
  - adds not_listed_label if it is missing, and
  - keeps the old allow_not_listed column but gives it a database default, so code
    that doesn't know about it can still insert questions.
On a database that ran the final 0046 it changes nothing.
"""
from django.db import migrations


def columns(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return {c.name for c in schema_editor.connection.introspection.get_table_description(cursor, table)}


def repair(apps, schema_editor):
    Question = apps.get_model('surveys', 'Question')
    table = Question._meta.db_table
    existing = columns(schema_editor, table)
    quote = schema_editor.quote_name
    postgres = schema_editor.connection.vendor == 'postgresql'

    if 'not_listed_label' not in existing:
        schema_editor.add_field(Question, Question._meta.get_field('not_listed_label'))
        if postgres:
            schema_editor.execute(f"ALTER TABLE {quote(table)} ALTER COLUMN {quote('not_listed_label')} SET DEFAULT ''")

    if 'allow_not_listed' in existing and postgres:
        schema_editor.execute(f"ALTER TABLE {quote(table)} ALTER COLUMN {quote('allow_not_listed')} SET DEFAULT false")


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0047_charity_and_category_reward'),
    ]

    operations = [
        migrations.RunPython(repair, migrations.RunPython.noop),
    ]
