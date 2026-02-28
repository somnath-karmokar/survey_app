from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Sum
from .models import UserProfile, SurveyResponse
from .forms import EditProfileForm
from datetime import timedelta
from django.http import JsonResponse, Http404, HttpResponse
from django.views.generic import ListView
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
from .models import (
    SurveyCategory, Survey, Question, 
    Choice, SurveyResponse, Answer, LuckyDrawEntry
)
from .forms import SurveyResponseForm
import random
from django.conf import settings
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.cache import never_cache


@login_required
def get_completed_categories_count(user):
    """Helper function to get the number of unique categories a user has completed surveys in."""
    return SurveyResponse.objects.filter(
        user=user,
        completed_at__isnull=False
    ).values('survey__category').distinct().count()

def should_show_advertisement(request):
    if not request.user.is_authenticated:
        return False

    # Initialize counter if it doesn't exist
    if 'ad_counter' not in request.session:
        request.session['ad_counter'] = 0
        request.session.modified = True
        print("DEBUG: should_show_advertisement - Initialized ad_counter to 0")
    
    # Show ad after every N completed surveys (configurable)
    AD_FREQUENCY = getattr(settings, 'SURVEY_CONFIG', {}).get('AD_FREQUENCY', 4)  # Show ad after every 2 surveys
    
    # Check if we've reached the frequency threshold
    should_show = request.session.get('ad_counter', 0) >= AD_FREQUENCY
    
    print(f"DEBUG: should_show_advertisement - "
          f"Counter: {request.session.get('ad_counter', 0)}, "
          f"Frequency: {AD_FREQUENCY}, "
          f"Show Ad: {should_show}")
    
    return should_show

@require_http_methods(["POST"])
@csrf_exempt
def survey_ad_shown(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Not authenticated'}, status=401)

    try:
        data = json.loads(request.body)
        reset_counter = data.get('reset', False)
        
        if reset_counter:
            # Reset the counter
            request.session['ad_counter'] = 0
            # Clear the redirect URL after using it
            redirect_url = request.session.pop('redirect_after_ad', {}).get('url', '')
            request.session.modified = True
            return JsonResponse({
                'status': 'success',
                'redirect_url': redirect_url or None
            })
        else:
            # Just acknowledge the ad was shown
            return JsonResponse({'status': 'success'})
            
    except Exception as e:
        print(f"DEBUG: survey_ad_shown - Error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def survey_list(request):
    # ... your existing code ...
    
    # Check if we should show an ad
    show_ad = False
    if request.user.is_authenticated:
        show_ad = should_show_advertisement(request)
        # If we're showing an ad, reset the flag for next time
        if show_ad:
            request.session['show_ad_after_redirect'] = False
            request.session.modified = True
    
    context = {
        'categories': categories,
        'completed_surveys': completed_surveys,
        'locked_surveys': locked_surveys,
        'show_advertisement': show_ad,
        # ... other context variables ...
    }
    
    return render(request, 'surveys/survey_list.html', context)

@login_required
def take_survey(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id, is_active=True)
    current_month = timezone.now().month
    current_year = timezone.now().year

    # Check if user can take the survey
    can_take, message = survey.can_user_take_survey(request.user)
    if not can_take:
        messages.warning(request, message)
        return redirect('survey_list')
    
    if request.method == 'POST':
        form = SurveyResponseForm(survey, request.POST)
        if form.is_valid():
            # Create survey response with started_at timestamp
            response = SurveyResponse.objects.create(
                user=request.user,
                survey=survey,
                started_at=timezone.now()
            )
            
            # Save all answers
            for question in survey.questions.all():
                field_name = f'question_{question.id}'
                
                if question.question_type == 'text':
                    answer = Answer.objects.create(
                        response=response,
                        question=question,
                        text_answer=form.cleaned_data.get(field_name)
                    )
                elif question.question_type == 'rating':
                    answer = Answer.objects.create(
                        response=response,
                        question=question,
                        rating_value=form.cleaned_data.get(field_name)
                    )
                else:  # single_choice or multiple_choice
                    selected_choices = form.cleaned_data.get(field_name, [])
                    if not isinstance(selected_choices, list):
                        selected_choices = [selected_choices]
                    
                    answer = Answer.objects.create(
                        response=response,
                        question=question
                    )
                    answer.selected_choices.set(selected_choices)
            
            # Mark the survey as completed
            response.completed_at = timezone.now()
            response.save()
            
            # Check if we should show an advertisement
            if should_show_advertisement(request):
                request.session['show_ad_after_redirect'] = True
                request.session.save()
            
            messages.success(request, 'Thank you for completing the survey!')
            return redirect('survey_list')
    else:
        form = SurveyResponseForm(survey=survey)
    
    context = {
        'survey': survey,
        'form': form,
    }
    
    return render(request, 'surveys/take_survey.html', context)

@login_required
def lucky_draw_entry(request):
    """Legacy endpoint - redirected by urls so this should not be reached.
    In case it is called directly, send user to the modern view instead.
    """
    messages.info(request, "This legacy entry view is no longer used; please use the main lucky draw page.")
    return redirect('surveys:lucky_draw')
        
        messages.success(request, f'You have successfully entered the lucky draw with number {selected_number}!')
        return redirect('survey_list')
    
    return redirect('survey_list')

@login_required
def lucky_draw_status(request):
    """Deprecated status view - redirect to the new lucky draw page."""
    messages.info(request, "This endpoint is deprecated. Please use the main lucky draw interface.")
    return redirect('surveys:lucky_draw')

def category_detail(request, slug):
    """
    View to display a category and its subcategories and surveys
    """
    try:
        category = SurveyCategory.objects.get(slug=slug, parent__isnull=True)
    except SurveyCategory.DoesNotExist:
        raise Http404("Category not found")
    
    # Get active surveys in this category and its subcategories
    subcategory_ids = list(category.children.values_list('id', flat=True))
    subcategory_ids.append(category.id)
    
    surveys = Survey.objects.filter(
        category_id__in=subcategory_ids,
        is_active=True
    ).select_related('category')
    
    context = {
        'category': category,
        'surveys': surveys,
        'subcategories': category.children.all().order_by('order', 'name')
    }
    
    return render(request, 'surveys/category_detail.html', context)

# API view for checking if a number is available
@login_required
def check_number_available(request):
    if request.method == 'GET' and 'number' in request.GET:
        try:
            number = int(request.GET.get('number'))
            current_month = timezone.now().month
            current_year = timezone.now().year
            
            is_taken = LuckyDrawEntry.objects.filter(
                month=current_month,
                year=current_year,
                selected_number=number
            ).exists()
            
            return JsonResponse({
                'available': not is_taken,
                'number': number
            })
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid number'}, status=400)
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def user_profile(request):
    user = request.user
    completed_surveys = SurveyResponse.objects.filter(
        user=user,
        completed_at__isnull=False
    ).count()
    
    # Get or create user profile
    user_profile, created = UserProfile.objects.get_or_create(user=user)
    
    # Sample data - replace with your actual data
    recent_activities = [
        {
            'title': 'Completed "Consumer Preferences Survey"',
            'date': timezone.now() - timedelta(hours=2),
            'icon': 'check-circle'
        },
        {
            'title': 'Earned 50 points',
            'date': timezone.now() - timedelta(days=1),
            'icon': 'coins'
        }
    ]
    
    context = {
        'user': user,
        'user_profile': user_profile,
        'completed_surveys': completed_surveys,
        'points_earned': getattr(user, 'points', 0),  # Update with your points field
        'user_level': 'Silver',  # Update with your level logic
        'recent_activities': recent_activities,
        'survey_progress': 75,  # Calculate based on user's progress
        'points_progress': 45,  # Calculate based on points
        'level_progress': 60,   # Calculate based on level
    }
    return render(request, 'surveys/profile.html', context)


# surveys/views.py
@login_required
def edit_profile(request):
    # Get or create user profile
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        form = EditProfileForm(request.POST, request.FILES, instance=user_profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated!')
            return redirect('surveys:user_profile')
    else:
        form = EditProfileForm(instance=user_profile)
    
    return render(request, 'surveys/edit_profile.html', {
        'form': form,
        'active_tab': 'profile'
    })

@login_required
def debug_ad(request):
    """Debug view to check advertisement status"""
    # Get completed surveys count
    completed_surveys = SurveyResponse.objects.filter(
        user=request.user,
        completed_at__isnull=False
    ).count()
    
    # Get ad counter from session
    ad_counter = request.session.get('ad_counter', 0)
    
    # Check if we should show an ad
    should_show = should_show_advertisement(request)
    
    # Get debug info from session
    debug_info = request.session.get('debug_info', [])
    
    # Prepare session data (excluding sensitive info)
    session_data = {
        k: v for k, v in request.session.items() 
        if k not in ['_auth_user_hash', '_auth_user_backend', '_auth_user_id']
    }
    
    # Prepare context
    context = {
        'ad_counter': ad_counter,
        'debug_info': debug_info,
        'completed_surveys': completed_surveys,
        'should_show_ad': should_show,
        'session_keys': list(request.session.keys()),
        'session_data': session_data,
        'request_path': request.path,
        'request_method': request.method,
        'request_meta': {k: v for k, v in request.META.items() if k in [
            'HTTP_USER_AGENT', 'REMOTE_ADDR', 'HTTP_REFERER'
        ]},
    }
    
    # Print debug info to console
    print("\n" + "="*80)
    print("DEBUG AD VIEW")
    print(f"User: {request.user}")
    print(f"Completed Surveys: {completed_surveys}")
    print(f"Ad Counter: {ad_counter}")
    print(f"Should Show Ad: {should_show}")
    print("="*80 + "\n")
    
    return render(request, 'surveys/debug_ad.html', context)


@xframe_options_sameorigin
@never_cache
def question_admin_js(request):
    js_content = """
    (function($) {
        'use strict';
        
        function updateSurveys() {
            var categoryId = $('#id_category').val() || '';
            var regionId = $('#id_region').val() || '';
            
            if (!categoryId && !regionId) {
                return;
            }
            
            // Get the select element from the filter_horizontal widget
            var $from = $('select#id_surveys_from');
            var $to = $('select#id_surveys_to');
            
            // Show loading
            $from.prop('disabled', true).html('<option>Loading surveys...</option>');
            
            // Get surveys based on category and region
            $.get('/admin/surveys/question/get-surveys/', {
                category_id: categoryId,
                region_id: regionId
            }, function(data) {
                // Clear and repopulate the "from" select
                $from.empty();
                $.each(data, function(index, survey) {
                    // Check if this survey is already in the "to" list
                    if ($('#id_surveys_to option[value="' + survey.id + '"]').length === 0) {
                        $from.append(new Option(survey.name, survey.id));
                    }
                });
                
                // Reinitialize the select boxes
                if (typeof SelectBox != 'undefined') {
                    SelectBox.init('id_surveys_from');
                    SelectBox.init('id_surveys_to');
                    SelectFilter.refresh_icons('id_surveys');
                }
                
                $from.prop('disabled', false);
            }).fail(function() {
                $from.html('<option>Error loading surveys</option>').prop('disabled', false);
            });
        }
        
        $(document).ready(function() {
            // Only run on the question add/change form
            if ($('#question_form').length === 0) return;
            
            // Initialize the filter
            updateSurveys();
            
            // Update when category or region changes
            $('#id_category, #id_region').on('change', function() {
                updateSurveys();
            });
            
            // Handle the move buttons
            $(document).on('click', '.selector-chooseall', function(e) {
                e.preventDefault();
                SelectBox.move_all("id_surveys_from", "id_surveys_to");
                SelectFilter.refresh_icons('id_surveys');
            });
            
            $(document).on('click', '.selector-add', function(e) {
                e.preventDefault();
                SelectBox.move("id_surveys_from", "id_surveys_to");
                SelectFilter.refresh_icons('id_surveys');
            });
            
            $(document).on('click', '.selector-remove', function(e) {
                e.preventDefault();
                SelectBox.move("id_surveys_to", "id_surveys_from");
                SelectFilter.refresh_icons('id_surveys');
            });
            
            $(document).on('click', '.selector-clearall', function(e) {
                e.preventDefault();
                SelectBox.move_all("id_surveys_to", "id_surveys_from");
                SelectFilter.refresh_icons('id_surveys');
            });
        });
    })(django.jQuery || (window.jQuery && jQuery.noConflict(true)));
    """
    response = HttpResponse(js_content, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache, no-store'
    return response