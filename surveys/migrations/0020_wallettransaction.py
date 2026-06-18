# Generated manually because Django is not installed in the active shell environment.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('surveys', '0019_userprofile_wallet_balance'),
    ]

    operations = [
        migrations.CreateModel(
            name='WalletTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('credit', 'Credit'), ('debit', 'Debit')], max_length=10)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('currency_code', models.CharField(default='USD', max_length=10)),
                ('currency_symbol', models.CharField(default='$', max_length=5)),
                ('description', models.CharField(max_length=255)),
                ('balance_after', models.DecimalField(decimal_places=2, max_digits=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('lucky_draw_entry', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='wallet_transaction', to='surveys.luckydrawentry')),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wallet_transactions', to='surveys.userprofile')),
            ],
            options={
                'verbose_name': 'Wallet Transaction',
                'verbose_name_plural': 'Wallet Transactions',
                'ordering': ['-created_at'],
            },
        ),
    ]
