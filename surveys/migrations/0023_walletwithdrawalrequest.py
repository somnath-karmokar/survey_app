# Generated manually because Django is not installed in the active shell environment.

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('surveys', '0022_alter_milestoneachievement_milestone_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='WalletWithdrawalRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(help_text='Name as it appears on the payment account.', max_length=160)),
                ('email', models.EmailField(max_length=254)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('currency_code', models.CharField(default='USD', max_length=10)),
                ('currency_symbol', models.CharField(default='$', max_length=5)),
                ('payment_method', models.CharField(choices=[('paypal', 'PayPal'), ('bank_transfer', 'Direct Bank Transfer'), ('gift_card', 'Gift Card')], max_length=20)),
                ('paypal_email', models.EmailField(blank=True, max_length=254)),
                ('bank_account_name', models.CharField(blank=True, max_length=160)),
                ('bank_name', models.CharField(blank=True, max_length=160)),
                ('bank_account_number', models.CharField(blank=True, max_length=64)),
                ('routing_number', models.CharField(blank=True, max_length=32)),
                ('sort_code', models.CharField(blank=True, max_length=32)),
                ('iban', models.CharField(blank=True, max_length=64)),
                ('nuban_number', models.CharField(blank=True, max_length=32, verbose_name='NUBAN account number')),
                ('transit_number', models.CharField(blank=True, max_length=32)),
                ('institution_number', models.CharField(blank=True, max_length=32)),
                ('gift_card_brand', models.CharField(blank=True, max_length=80)),
                ('gift_card_email', models.EmailField(blank=True, max_length=254)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], db_index=True, default='pending', max_length=20)),
                ('admin_note', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('country', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='surveys.country')),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='withdrawal_requests', to='surveys.userprofile')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_withdrawal_requests', to=settings.AUTH_USER_MODEL)),
                ('wallet_transaction', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='withdrawal_request', to='surveys.wallettransaction')),
            ],
            options={
                'verbose_name': 'Wallet Withdrawal Request',
                'verbose_name_plural': 'Wallet Withdrawal Requests',
                'ordering': ['-created_at'],
            },
        ),
    ]
