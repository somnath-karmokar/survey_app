"""Wallet reward for completing a whole survey category.

Every completed category (all parts, ~120 questions) adds
CountryLuckyDrawConfig.category_completion_reward to the user's wallet: 2.00 by
default (SURVEY_CONFIG['CATEGORY_COMPLETION_REWARD']), 1.00 for Nigeria. Each
completed SurveyResponse is rewarded at most once (WalletTransaction.survey_response).
"""
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from .models import CountryLuckyDrawConfig, UserProfile, WalletTransaction


def category_completion_reward(profile):
    """The reward amount for this user's country (Decimal; 0 means no reward)."""
    config = None
    if profile.country_id:
        config = CountryLuckyDrawConfig.objects.filter(country_id=profile.country_id, is_active=True).first()
    if config is not None and config.category_completion_reward is not None:
        return config.category_completion_reward
    survey_config = getattr(settings, 'SURVEY_CONFIG', {})
    code = str(getattr(profile.country, 'code', '') or '').upper() if profile.country_id else ''
    by_country = survey_config.get('CATEGORY_COMPLETION_REWARD_BY_COUNTRY', {'NG': '1.00'})
    return Decimal(str(by_country.get(code, survey_config.get('CATEGORY_COMPLETION_REWARD', '2.00'))))


def credit_category_completion(response):
    """Add the category reward to the wallet for a just-completed response.

    Returns the WalletTransaction, or None when there's no reward or it was
    already paid.
    """
    with transaction.atomic():
        profile = UserProfile.objects.select_for_update().get(user_id=response.user_id)
        if WalletTransaction.objects.filter(survey_response=response).exists():
            return None
        amount = category_completion_reward(profile)
        if amount <= 0:
            return None
        profile.wallet_balance = (profile.wallet_balance or Decimal('0')) + amount
        UserProfile.objects.filter(pk=profile.pk).update(wallet_balance=profile.wallet_balance)
        return WalletTransaction.objects.create(
            profile=profile,
            transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
            amount=amount,
            currency_code=profile.wallet_currency_code,
            currency_symbol=profile.wallet_currency_symbol,
            description=f'Survey category completed: {response.survey.category.name}'[:255],
            survey_response=response,
            balance_after=profile.wallet_balance,
        )
