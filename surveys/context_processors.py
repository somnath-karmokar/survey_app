from .models import SurveyCategory

def categories_processor(request):
    """
    Context processor that makes all categories available in all templates.
    """
    categories = SurveyCategory.objects.filter(parent__isnull=True).order_by('order', 'name')
    return {
        'categories': categories,
    }
