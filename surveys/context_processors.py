from django.conf import settings
from .models import SurveyCategory

def categories_processor(request):
    """
    Context processor that makes all categories available in all templates.
    """
    categories = SurveyCategory.objects.filter(parent__isnull=True).order_by('order', 'name')
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
