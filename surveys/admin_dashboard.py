"""Figures and model groups for the admin home page (templates/admin/index.html)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Sum
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

# Admin home page sections: (title, icon, description, model object names in order).
SECTIONS = [
    ('Surveys', 'clipboard', 'Survey catalogue and what users answered', [
        'SurveyResponse', 'SurveyCategory', 'Survey', 'Question', 'Choice', 'Answer']),
    ('Users & safety', 'users', 'Accounts, suspensions and verification', [
        'User', 'SurveySuspension', 'EmailVerification', 'Group']),
    ('Wallet & payouts', 'wallet', 'Balances, transactions, withdrawals and donations', [
        'WalletWithdrawalRequest', 'WalletTransaction', 'UserWallet', 'Charity']),
    ('Draws & rewards', 'gift', 'Quick and Poll draws, prizes and milestones', [
        'LuckyDrawEntry', 'CountryLuckyDrawConfig', 'MilestoneAchievement',
        'MonthlyDrawEligibleUser', 'MonthlyDrawNumbers', 'MonthlyDrawSettlement']),
    ('Polls', 'chart', 'Polls shown on the home page', [
        'Poll', 'PollQuestion', 'PollChoice', 'PollResponse', 'PollAnswer']),
    ('Website & marketing', 'globe', 'Countries, pages, adverts and the journal', [
        'Country', 'Advertiser', 'DirectMarketing', 'JournalPost', 'JournalCategory', 'AboutUs', 'PrivacyPolicy']),
]


def grouped_models(app_list):
    """The registered models (from AdminSite.get_app_list) arranged into SECTIONS.

    Anything not listed lands in an "Other" section, so nothing disappears.
    """
    models = {m['object_name']: m for app in app_list for m in app['models']}
    sections, used = [], set()
    for title, icon, description, names in SECTIONS:
        items = [models[n] for n in names if n in models]
        used.update(n for n in names if n in models)
        if items:
            sections.append({'title': title, 'icon': icon, 'description': description, 'models': items})
    rest = [m for n, m in models.items() if n not in used]
    if rest:
        sections.append({'title': 'Other', 'icon': 'grid', 'description': '', 'models': rest})
    return sections


def _url(site_name, name, query=''):
    try:
        return reverse(f'{site_name}:{name}') + query
    except NoReverseMatch:
        return ''


def dashboard_stats(site_name):
    """Key figures for the admin home page, each with a link to the matching list."""
    from .models import (
        LuckyDrawEntry, SurveyResponse, SurveySuspension, UserProfile, WalletWithdrawalRequest,
    )
    from .admin import format_duration

    now = timezone.now()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    week = now - timedelta(days=7)
    users = get_user_model().objects.filter(is_staff=False)
    completed = SurveyResponse.objects.filter(completed_at__isnull=False)
    week_completed = completed.filter(completed_at__gte=week)
    avg_seconds = week_completed.filter(time_spent_seconds__gt=0).aggregate(a=Avg('time_spent_seconds'))['a']
    pending = WalletWithdrawalRequest.objects.filter(status=WalletWithdrawalRequest.STATUS_PENDING)
    responses = 'surveys_surveyresponse_changelist'

    cards = [
        {'label': 'Users', 'value': users.count(), 'icon': 'users', 'tone': 'blue',
         'note': f'+{users.filter(date_joined__gte=week).count()} in the last 7 days',
         'url': _url(site_name, 'auth_user_changelist')},
        {'label': 'Surveys completed today', 'value': completed.filter(completed_at__gte=today).count(),
         'icon': 'check', 'tone': 'green', 'note': f'{week_completed.count()} in the last 7 days · {completed.count()} in total',
         'url': _url(site_name, responses, '?status=completed')},
        {'label': 'Surveys in progress', 'value': SurveyResponse.objects.filter(completed_at__isnull=True).count(),
         'icon': 'clock', 'tone': 'amber', 'note': 'started, not finished yet',
         'url': _url(site_name, responses, '?status=in_progress')},
        {'label': 'Average time per survey', 'value': format_duration(avg_seconds) if avg_seconds else '–',
         'icon': 'timer', 'tone': 'violet', 'note': 'completed in the last 7 days',
         'url': _url(site_name, responses, '?status=completed&o=-7')},
        {'label': 'Suspended users', 'value': UserProfile.objects.filter(suspended_until__gt=now).count(),
         'icon': 'lock', 'tone': 'red', 'note': f'{SurveySuspension.objects.filter(suspended_at__gte=week).count()} new in the last 7 days',
         'url': _url(site_name, 'surveys_surveysuspension_changelist')},
        {'label': 'Pending withdrawals', 'value': pending.count(), 'icon': 'wallet', 'tone': 'teal',
         'note': f'{pending.filter(payment_method=WalletWithdrawalRequest.PAYMENT_METHOD_CHARITY).count()} of them charity donations',
         'url': _url(site_name, 'surveys_walletwithdrawalrequest_changelist', '?status__exact=pending')},
        {'label': 'Quick draw plays today', 'value': LuckyDrawEntry.objects.filter(created_at__gte=today).count(),
         'icon': 'gift', 'tone': 'pink',
         'note': f'{LuckyDrawEntry.objects.filter(created_at__gte=week, is_winner=True).count()} winners in the last 7 days',
         'url': _url(site_name, 'surveys_luckydrawentry_changelist')},
    ]

    recent = (completed.select_related('user', 'survey__category__country').order_by('-completed_at')[:8])
    recent_rows = [{
        'name': r.user.get_full_name() or r.user.username,
        'email': r.user.email,
        'category': r.survey.category.name,
        'country': getattr(r.survey.category.country, 'name', ''),
        'time': format_duration(r.time_spent_seconds),
        'completed_at': r.completed_at,
        'url': reverse(f'{site_name}:surveys_surveyresponse_change', args=[r.pk]),
    } for r in recent]

    top_categories = (week_completed.values('survey__category__name')
                      .annotate(n=Count('id'), avg=Avg('time_spent_seconds')).order_by('-n')[:5])
    top_rows = [{'name': t['survey__category__name'], 'count': t['n'],
                 'avg': format_duration(t['avg']) if t['avg'] else '–'} for t in top_categories]

    return {
        'dashboard_cards': cards,
        'recent_completions': recent_rows,
        'recent_completions_url': _url(site_name, responses, '?status=completed'),
        'top_categories': top_rows,
        'donations_total': WalletWithdrawalRequest.objects.filter(
            payment_method=WalletWithdrawalRequest.PAYMENT_METHOD_CHARITY,
            status=WalletWithdrawalRequest.STATUS_APPROVED).aggregate(t=Sum('charity_total_amount'))['t'],
    }
