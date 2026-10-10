from django.utils import timezone
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class AutoLogoutMiddleware:
    """Middleware to automatically log out users after a period of inactivity.

    Stores the last activity timestamp in the session and compares on each request.
    If more than two hours (7200 seconds) have passed since the last recorded
    activity, the user is logged out.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only enforce for authenticated users
        if request.user.is_authenticated:
            now = timezone.now()
            last_activity = request.session.get('last_activity')
            if last_activity:
                try:
                    last = datetime.fromisoformat(last_activity)
                except Exception:
                    last = None
                if last:
                    elapsed = (now - last).total_seconds()
                    # 2 hours = 7200 seconds
                    if elapsed > 7200:
                        logout(request)
                        # Optional: add a message to inform user
                        # from django.contrib import messages
                        # messages.info(request, "You have been logged out due to inactivity.")
            # update last activity whether or not we logged the user out
            request.session['last_activity'] = now.isoformat()

        response = self.get_response(request)
        return response


class MonthlyDrawSettlementMiddleware:
    """Settles ended Monthly draw days from normal site traffic, so no cron job is needed.

    Only active in the few days after a draw day: the 1st-4th of the month in UTC
    (every country's 1st has ended by the 2nd-ish UTC, depending on its time zone)
    plus the 3 days after LUCKY_DRAW_CONFIG['MONTHLY_DRAW_TEST_DATE']. On any
    other day it does nothing. Inside that window, at most once every CHECK_EVERY
    seconds per server process, every Monthly-draw country is checked on its own
    clock and any ended draw day is settled (paying out where the draw couldn't
    run). Each country and day is settled once, so extra checks are harmless. A
    failure here is logged and never affects the visitor's page.
    """
    CHECK_EVERY = 600
    CACHE_KEY = 'monthly-draw-settlement-check'
    DAYS_AFTER_DRAW = 3

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith(('/static/', '/media/')) and self.in_settlement_window():
            self.settle_if_due()
        return response

    def in_settlement_window(self):
        from django.conf import settings
        today = timezone.now().date()
        if today.day <= 1 + self.DAYS_AFTER_DRAW:
            return True
        test_date = settings.LUCKY_DRAW_CONFIG.get('MONTHLY_DRAW_TEST_DATE')
        if test_date:
            try:
                days_after = (today - datetime.fromisoformat(test_date).date()).days
                if 0 <= days_after <= self.DAYS_AFTER_DRAW:
                    return True
            except ValueError:
                pass
        # Earlier test draw days (the setting may have moved on since): checked
        # at most every CHECK_EVERY seconds, so most requests skip the query.
        from django.core.cache import cache
        recent = cache.get('monthly-draw-recent-test-days')
        if recent is None:
            from .models import MonthlyDrawDay
            recent = MonthlyDrawDay.objects.filter(
                draw_date__gte=today - timedelta(days=self.DAYS_AFTER_DRAW + 1),
            ).exists()
            cache.set('monthly-draw-recent-test-days', recent, self.CHECK_EVERY)
        return recent

    def settle_if_due(self):
        from django.core.cache import cache
        if not cache.add(self.CACHE_KEY, True, self.CHECK_EVERY):
            return
        try:
            from .lucky_draw import LuckyDrawView
            from .models import CountryLuckyDrawConfig
            view = LuckyDrawView()
            configs = CountryLuckyDrawConfig.objects.filter(
                is_active=True, monthly_prize_amount__isnull=False,
            ).select_related('country')
            for config in configs:
                view.settle_due_monthly_draws(config)
        except Exception:
            logger.exception("Monthly draw settlement check failed")


class ExceptionRedirectMiddleware:
    """Catch unhandled exceptions and redirect to home instead of showing an error.

    This prevents debug/error tracebacks from being displayed in the UI.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Exclude ads.txt from redirect logic (needed for Google AdSense)
        if request.path == '/ads.txt':
            return self.get_response(request)

        try:
            response = self.get_response(request)
        except (Http404, PermissionDenied):
            logger.warning(
                "Redirecting to home after handled error: %s %s (referer: %s, user agent: %s)",
                request.method, request.get_full_path(),
                request.META.get('HTTP_REFERER', '-'), request.META.get('HTTP_USER_AGENT', '-'),
                exc_info=True,
            )
            return redirect('surveys:home')
        except Exception as exc:
            logger.exception("Unhandled exception caught by ExceptionRedirectMiddleware")
            # Redirect to home page (change this if you'd like a different landing page)
            return redirect('surveys:home')

        if response.status_code in (403, 404, 500):
            logger.warning(
                "Redirecting to home after error response with status %s: %s %s (referer: %s, user agent: %s)",
                response.status_code, request.method, request.get_full_path(),
                request.META.get('HTTP_REFERER', '-'), request.META.get('HTTP_USER_AGENT', '-'),
            )
            return redirect('surveys:home')

        return response
