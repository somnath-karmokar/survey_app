from django.utils import timezone
from django.contrib.auth import logout
from datetime import datetime


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
