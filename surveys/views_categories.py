from traceback import print_tb
from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView
from .models import SurveyCategory, Survey, SurveyResponse, UserProfile
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings  # Add this import
from .views import should_show_advertisement
from django.utils import timezone
from django.db.models import Sum

class CategoryListView(ListView):
    model = SurveyCategory
    template_name = 'surveys/category_list.html'
    context_object_name = 'categories'
    
    def get_queryset(self):
        # Start with base queryset
        queryset = SurveyCategory.objects.all()
        
        # Check if user is authenticated
        if not self.request.user.is_authenticated:
            return queryset.none()
            
        # Get or create user profile
        try:
            user_profile, created = UserProfile.objects.get_or_create(
                user=self.request.user,
                defaults={'user_type': 'frontend'}
            )
            
            user_country = user_profile.country
            print(f'User country: {user_country}')
            
            # If user has a country, filter by it
            if user_country:
                return queryset.filter(country=user_country)
                
        except Exception as e:
            print(f"Error getting user country: {str(e)}")
        
        # Return all categories if no country filter applies
        return queryset.filter(parent__isnull=True).order_by('order', 'name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add user's country to context for template use if needed
        try:
            context['user_country'] = self.request.user.userprofile.country
        except:
            context['user_country'] = None
        
        # Add lucky draw eligibility status
        if self.request.user.is_authenticated:
            from .lucky_draw import LuckyDrawView
            lucky_draw_view = LuckyDrawView()
            context['is_eligible_for_draw'] = lucky_draw_view.is_eligible(self.request.user)
            
            # Add progress information
            from .models import UserSurveyProgress
            total_surveys = self.request.user.survey_progress.aggregate(
                total=Sum('completed_count')
            )['total'] or 0
            required_surveys = getattr(settings, 'LUCKY_DRAW_CONFIG', {}).get('SURVEYS_REQUIRED', 3)
            context['surveys_completed'] = total_surveys
            context['surveys_required'] = required_surveys
            context['surveys_remaining'] = max(0, required_surveys - total_surveys)
            context['progress_percent'] = min(100, (total_surveys / required_surveys) * 100) if required_surveys > 0 else 0
        
        return context
        

class CategoryDetailView(DetailView):
    model = SurveyCategory
    template_name = 'surveys/category_detail.html'
    context_object_name = 'category'
    slug_url_kwarg = 'category_slug'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.get_object()
        surveys = category.surveys.filter(is_active=True).order_by('level', 'id')
        
        # Initialize user's highest level
        user_highest_level = 0
        completed_surveys = {}
        
        if self.request.user.is_authenticated:
            from .lucky_draw import LuckyDrawView
            lucky_draw_view = LuckyDrawView()
            context['is_eligible_for_draw'] = lucky_draw_view.is_eligible(self.request.user)
            
            # Add progress information
            from .models import UserSurveyProgress
            total_surveys = self.request.user.survey_progress.aggregate(
                total=Sum('completed_count')
            )['total'] or 0
            required_surveys = getattr(settings, 'LUCKY_DRAW_CONFIG', {}).get('SURVEYS_REQUIRED', 3)
            context['surveys_completed'] = total_surveys
            context['surveys_required'] = required_surveys
            context['surveys_remaining'] = max(0, required_surveys - total_surveys)
            context['progress_percent'] = min(100, (total_surveys / required_surveys) * 100) if required_surveys > 0 else 0
            
            # Get all completed surveys for this user in this category
            completed_responses = SurveyResponse.objects.filter(
                user=self.request.user,
                survey__category=category,
                completed_at__isnull=False
            ).select_related('survey')
            
            # Create a dictionary of completed surveys with their completion times
            for response in completed_responses:
                survey_id = response.survey_id
                if survey_id not in completed_surveys or completed_surveys[survey_id] < response.completed_at:
                    completed_surveys[survey_id] = response.completed_at
                    # Update highest level if this survey is from a higher level
                    if response.survey.level > user_highest_level:
                        user_highest_level = response.survey.level

        # Process each survey
        surveys_with_status = []
        for survey in surveys:
            is_completed = survey.id in completed_surveys
            last_completed = completed_surveys.get(survey.id)
            is_locked = survey.level > (user_highest_level + 1)
            lock_message = f"Complete Level {survey.level - 1} surveys to unlock" if is_locked else ""
            days_since_completion = (timezone.now() - last_completed).days if last_completed else None
            can_retake = bool(last_completed and days_since_completion >= settings.SURVEY_CONFIG.get('DEFAULT_COOLDOWN_DAYS', 10))
            
            surveys_with_status.append({
                'survey': survey,
                'is_completed': is_completed,
                'is_locked': is_locked,
                'lock_message': lock_message,
                'last_completed': last_completed,
                'days_since_completion': days_since_completion,
                'can_retake': can_retake
            })

        context.update({
            'surveys': surveys_with_status,
            'now': timezone.now(),
            'cooldown_days': settings.SURVEY_CONFIG.get('DEFAULT_COOLDOWN_DAYS', 10),
            'user_highest_level': user_highest_level,
            'show_advertisement': should_show_advertisement(self.request)
        })
        
        return context

@login_required
def category_surveys(request, category_slug):
    category = get_object_or_404(SurveyCategory, slug=category_slug, is_active=True)
    surveys = category.surveys.filter(is_active=True)
    
    # Get completed surveys
    completed_surveys = SurveyResponse.objects.filter(
        user=request.user,
        survey__in=surveys,
        completed_at__isnull=False
    ).values_list('survey_id', flat=True)
    
    # Check if any survey in this category is completed
    category_completed = SurveyResponse.objects.filter(
        user=request.user,
        survey__category=category,
        completed_at__isnull=False
    ).exists()
    
    # Add lock status to each survey
    surveys_with_status = []
    for survey in surveys:
        is_locked, message = survey.is_locked_for_user(request.user)
        surveys_with_status.append({
            'survey': survey,
            'is_completed': survey.id in completed_surveys,
            'is_locked': is_locked,
            'lock_message': message,
        })
    
    context = {
        'category': category,
        'surveys': surveys_with_status,
        'category_completed': category_completed,
    }
    return render(request, 'surveys/category_surveys.html', context)
