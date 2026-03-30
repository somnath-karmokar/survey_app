from django.utils import timezone
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from datetime import datetime
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


class ExceptionRedirectMiddleware:
    """Catch unhandled exceptions and redirect to home instead of showing an error.

    This prevents debug/error tracebacks from being displayed in the UI.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except (Http404, PermissionDenied):
            logger.warning("Redirecting to home after handled error", exc_info=True)
            return redirect('surveys:home')
        except Exception as exc:
            logger.exception("Unhandled exception caught by ExceptionRedirectMiddleware")
            # Redirect to home page (change this if you'd like a different landing page)
            return redirect('surveys:home')

        if response.status_code in (403, 404, 500):
            logger.warning(
                "Redirecting to home after error response with status %s",
                response.status_code,
            )
            return redirect('surveys:home')

        return response
