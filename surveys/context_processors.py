from django.conf import settings
from .models import SurveyCategory

def categories_processor(request):
    """
    Context processor that makes all categories available in all templates.
    """
    categories = SurveyCategory.objects.filter(parent__isnull=True).order_by('?')
    return {
        'categories': categories,
    }

def bitlabs_processor(request):
    """
    Makes the BitLabs (bitlabs.ai) app token available in all templates.
    """
    return {
        'bitlabs_app_token': settings.BITLABS_APP_TOKEN,
    }


def suspension_processor(request):
    """Whether the logged-in user is suspended (untruthful survey answer), for every page.

    Templates use `account_suspended_until` to show the suspension banner and to
    turn Start/Retake survey buttons into a disabled "Suspended" button.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    profile = getattr(user, 'profile', None)
    if profile is None or not profile.is_suspended:
        return {}
    from .models import UserProfile
    return {
        'account_suspended_until': profile.suspended_until,
        'account_suspension_message': UserProfile.SUSPENSION_MESSAGE,
    }


def open_survey_processor(request):
    """The logged-in user's unfinished survey, so Start buttons can say "Continue"
    and other categories' buttons can say "Finish ... first" (one category at a time)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    from .survey_progress import open_response
    response = open_response(user)
    if response is None:
        return {}
    return {
        'open_survey_id': response.survey_id,
        'open_survey_category': response.survey.category.name,
    }
