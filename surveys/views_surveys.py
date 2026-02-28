from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, F
from django import forms
from django.utils import timezone
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import send_mail, EmailMultiAlternatives
from django.utils.html import strip_tags

from .models import Survey, SurveyCategory, Question, UserSurveyProgress, SurveyResponse, Answer, LuckyDrawEntry
from .views import should_show_advertisement
from .forms import SurveyResponseForm
from .emails import send_survey_completion_email, send_lucky_draw_entry_email

# surveys/views_surveys.py
@login_required
def survey_list(request):
    # Get all active categories that have active surveys
    categories = SurveyCategory.objects.filter(
        surveys__is_active=True
    ).distinct().prefetch_related('surveys')
    
    # Get all surveys the user has completed
    completed_responses = SurveyResponse.objects.filter(
        user=request.user,
        completed_at__isnull=False
    ).select_related('survey')
    
    # Create a dictionary of survey_id: completed_at for quick lookup
    completed_surveys = {
        response.survey_id: response.completed_at 
        for response in completed_responses
    }
    
    # Get categories with completed surveys
    completed_categories = set(
        response.survey.category_id 
        for response in completed_responses
    )
    
    # Check if user has completed all available surveys (considering cooldown)
    active_surveys = Survey.objects.filter(is_active=True)
    all_surveys_completed = False
    
    if active_surveys.exists():
        all_surveys_completed = all(
            survey.id in completed_surveys and 
            (timezone.now() - completed_surveys[survey.id]).days < settings.SURVEY_CONFIG.get('DEFAULT_COOLDOWN_DAYS', 1)
            for survey in active_surveys
        )

    # Check if we need to show an ad after redirect (from survey completion)
    show_advertisement = False
    if request.session.get('show_ad_after_redirect', False):
        show_advertisement = True
        # Clear the flag so we don't show it again
        del request.session['show_ad_after_redirect']
        request.session.save()
        print("DEBUG: survey_list - Showing ad after survey completion")
    
    # Check if we should show an ad based on counter
    if not show_advertisement:
        show_advertisement = should_show_advertisement(request)
    
    context = {
        'categories': categories,
        'completed_surveys': completed_surveys,
        'completed_categories': completed_categories,
        'all_surveys_completed': all_surveys_completed,
        'show_advertisement': show_advertisement,
        'cooldown_days': settings.SURVEY_CONFIG.get('DEFAULT_COOLDOWN_DAYS', 1),
        'now': timezone.now()  # Add this line
    }
    return render(request, 'surveys/survey_list.html', context)

@login_required
def survey_detail(request, survey_id, question_index=0):
    """Display and handle survey questions with pagination"""
    survey = get_object_or_404(Survey, id=survey_id, is_active=True)

    # Check if user can take this survey based on cooldown
    can_take, message = survey.can_user_take_survey(request.user)
    if not can_take:
        messages.warning(request, message)
        return redirect('surveys:survey_list')

    # Allow users to retake surveys by removing the existing response check
    # Users can now retake surveys regardless of when they last completed them
    
    # Get all questions for this survey
    questions = list(survey.questions.all().order_by('order', 'id'))
    total_questions = len(questions)
    
    if not questions:
        messages.warning(request, 'This survey has no questions yet.')
        return redirect('surveys:survey_list')
    
    # Convert question_index to integer and ensure it's within bounds
    question_index = max(0, min(int(question_index), total_questions - 1))
    current_question = questions[question_index]
    
    # Handle form submission
    if request.method == 'POST':
        form = SurveyResponseForm(
            data=request.POST, 
            survey=survey,
            question_id=current_question.id
        )
        
        if form.is_valid():
            # Save the answer to session
            session_key = f'survey_{survey_id}_answers'
            answers = request.session.get(session_key, {})
            
            # Save current answer to session
            answers[str(current_question.id)] = form.cleaned_data.get(f'question_{current_question.id}')
            request.session[session_key] = answers
            
            # Check if we should show an ad based on AD_FREQUENCY setting (after every N questions, but not on first or last question)
            ad_frequency = getattr(settings, 'SURVEY_CONFIG', {}).get('AD_FREQUENCY', 3)
            
            # Check if ad has already been shown for this question
            ad_shown_key = f'survey_{survey_id}_ad_shown_q{question_index}'
            ad_already_shown = request.session.get(ad_shown_key, False)
            
            show_ad = False
            if question_index > 0 and (question_index + 1) % ad_frequency == 0 and question_index < total_questions - 1 and not ad_already_shown:
                show_ad = True
            
            # If showing ad, stay on current question but set flag to show ad
            if show_ad:
                # Mark that ad has been shown for this question
                request.session[ad_shown_key] = True
                request.session.save()
                
                return render(request, 'surveys/survey_detail.html', {
                    'survey': survey,
                    'form': form,
                    'current_question': current_question,
                    'question_index': question_index,
                    'total_questions': total_questions,
                    'progress': int(((question_index + 1) / total_questions) * 100),
                    'is_last_question': question_index == total_questions - 1,
                    'show_ad': True
                })
            
            # If not showing ad, proceed to next question or submit
            next_index = question_index + 1
            if next_index < total_questions:
                # Clear ad flag for current question when moving to next
                if ad_shown_key in request.session:
                    del request.session[ad_shown_key]
                    request.session.save()
                    
                return redirect('surveys:survey_question', 
                              survey_id=survey.id, 
                              question_index=next_index)
            else:
                # All questions answered, save to database
                survey_response = SurveyResponse.objects.create(
                    user=request.user,
                    survey=survey,
                    completed_at=timezone.now()
                )
                
                # Save all answers from session
                for q_id, answer_value in answers.items():
                    question = Question.objects.get(id=q_id)
                    answer = Answer(
                        response=survey_response,
                        question=question
                    )
                    answer.save()
                    
                    # Handle different question types
                    if question.question_type in ['multiple_choice', 'single_choice']:
                        if isinstance(answer_value, (list, tuple)):
                            answer.selected_choices.set(answer_value)
                        else:
                            answer.selected_choices.set([answer_value])
                    elif question.question_type == 'text':
                        answer.text_answer = str(answer_value)
                        answer.save()
                    elif question.question_type == 'rating':
                        answer.rating_value = int(answer_value)
                        answer.save()
                
                # Create the survey response with completion time
                response = SurveyResponse.objects.create(
                    user=request.user,
                    survey=survey,
                    completed_at=timezone.now()
                )
                
                # Update or create user's survey progress
                progress, created = UserSurveyProgress.objects.get_or_create(
                    user=request.user,
                    category=survey.category,
                    level=survey.level,
                    defaults={'completed_count': 1}
                )
                
                if not created:
                    # Only increment if the survey wasn't just created
                    # This ensures we don't double-count if the form is submitted multiple times
                    progress.completed_count = F('completed_count') + 1
                    progress.save(update_fields=['completed_count', 'last_completed'])
                    
                    # Refresh the instance to get the updated count
                    progress.refresh_from_db()
                
                print(f"Updated progress for {request.user.username} - {survey.category.name} (Level {survey.level}): {progress.completed_count} surveys completed")
                # Clear the session data
                if session_key in request.session:
                    del request.session[session_key]
                
                messages.success(request, 'Thank you for completing the survey!')
                return redirect('surveys:survey_complete', survey_id=survey.id)
    else:
        # For GET requests, ads should not be shown (only triggered during POST)
        show_ad = False
        
        # For GET requests, check if there's a previous answer in session
        session_key = f'survey_{survey_id}_answers'
        initial_data = {}
        previous_answer = request.session.get(session_key, {}).get(str(current_question.id))
        if previous_answer:
            initial_data[f'question_{current_question.id}'] = previous_answer
            
        form = SurveyResponseForm(
            survey=survey,
            question_id=current_question.id,
            initial=initial_data
        )
    
    # Calculate progress
    progress = int(((question_index + 1) / total_questions) * 100) if total_questions > 0 else 0
    
    return render(request, 'surveys/survey_detail.html', {
        'survey': survey,
        'form': form,
        'current_question': current_question,
        'question_index': question_index,
        'total_questions': total_questions,
        'progress': progress,
        'is_last_question': question_index == total_questions - 1,
        'show_ad': show_ad
    })

@login_required
def lucky_draw_entry(request):
    """Deprecated entry view - redirect to new LuckyDrawView."""
    messages.info(request, "This endpoint has been replaced by the new lucky draw interface.")
    return redirect('surveys:lucky_draw')

@login_required
def take_survey(request, survey_id, question_id=None):
    survey = get_object_or_404(Survey, id=survey_id, is_active=True)
    questions = list(survey.questions.all().order_by('order'))
    
    # Check if user has already completed this survey
    if SurveyResponse.objects.filter(
        user=request.user,
        survey=survey,
        completed_at__isnull=False
    ).exists():
        messages.warning(request, 'You have already completed this survey.')
        return redirect('surveys:survey_detail', survey_id=survey.id)
    
    
    # Handle form submission
    if request.method == 'POST':
        # Get the current question ID from the form data
        current_question_id = request.POST.get('current_question_id')
        
        # If it's the last question, process the entire form
        if 'submit_survey' in request.POST:
            form = SurveyResponseForm(survey, request.POST)
            if form.is_valid():
                # Process the form
                response = form.save(commit=False)
                response.user = request.user
                response.survey = survey
                response.completed_at = timezone.now()
                response.save()
                form.save_m2m()  # For many-to-many fields if any
                
                # Add this line to update the user's progress
                UserSurveyProgress.objects.update_or_create(
                    user=request.user,
                    category=survey.category,
                    level=survey.level,
                    defaults={'completed_count': 1},
                )

                # Or if you want to increment existing count:
                progress, created = UserSurveyProgress.objects.get_or_create(
                    user=request.user,
                    category=survey.category,
                    level=survey.level,
                    defaults={'completed_count': 1}
                )

                if not created:
                    progress.completed_count += 1
                    progress.save()

                # Clear the session data
                if 'survey_answers' in request.session:
                    del request.session['survey_answers']
                
                # Set flag to show ad after redirect
                request.session['ad_counter'] = request.session.get('ad_counter', 0) + 1
                AD_FREQUENCY = getattr(settings, 'SURVEY_CONFIG', {}).get('AD_FREQUENCY', 4)

                # Store category slug for redirection after ad
                request.session['redirect_after_ad'] = {
                    'url': reverse('surveys:category_detail', kwargs={'category_slug': survey.category.slug}),
                    'survey_id': survey.id
                }

                if request.session.get('ad_counter', 0) >= AD_FREQUENCY:
                    request.session['show_ad_after_redirect'] = True

                request.session.save()  # Explicitly save the session
                messages.success(request, 'Thank you for completing the survey!')
                return redirect('surveys:category_detail', category_slug=survey.category.slug)
        else:
            # For non-final submissions, just save the data in session
            if 'survey_answers' not in request.session:
                request.session['survey_answers'] = {}
            
            # Save the current question's answer
            try:
                question = Question.objects.get(id=current_question_id, surveys=survey)
                field_name = f'question_{question.id}'
                
                if question.question_type == 'multiple_choice':
                    request.session['survey_answers'][field_name] = request.POST.getlist(field_name, [])
                else:
                    request.session['survey_answers'][field_name] = request.POST.get(field_name, '')
                
                request.session.save()
                
                # Determine next question
                current_index = next((i for i, q in enumerate(questions) if str(q.id) == current_question_id), -1)
                if current_index < len(questions) - 1:
                    next_question = questions[current_index + 1]
                    return redirect('surveys:take_survey_with_question', survey_id=survey.id, question_id=next_question.id)
                else:
                    # If this was the last question, redirect to the final submission
                    return redirect('surveys:take_survey', survey_id=survey.id)
                    
            except Question.DoesNotExist:
                messages.error(request, 'Invalid question. Please start the survey again.')
                return redirect('surveys:survey_detail', survey_id=survey.id)
    
    # GET request or form invalid
    # Get the current question (first one if none specified)
    current_question = None
    current_index = 0
    total_questions = len(questions)
    
    if question_id:
        try:
            current_question = Question.objects.get(id=question_id, surveys=survey)
            current_index = next((i for i, q in enumerate(questions) if q.id == current_question.id), 0)
        except Question.DoesNotExist:
            messages.error(request, 'Invalid question. Please start the survey again.')
            return redirect('surveys:survey_detail', survey_id=survey.id)
    elif questions:
        current_question = questions[0]
    else:
        messages.warning(request, 'This survey has no questions yet.')
        return redirect('surveys:survey_detail', survey_id=survey.id)
    
    # Initialize form with session data if available
    initial_data = request.session.get('survey_answers', {})
    form = SurveyResponseForm(survey=survey, initial=initial_data)
    
    # For GET requests, we'll only show one question at a time
    if current_question:
        # Filter the form to only include the current question
        question_fields = [f'question_{current_question.id}']
        
        # Create a new form with only the current question
        class SingleQuestionForm(forms.Form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields = {k: v for k, v in form.fields.items() if k in question_fields}
                
                # Set initial values from session if available
                for field_name, field in self.fields.items():
                    if field_name in initial_data:
                        if isinstance(field, forms.MultipleChoiceField) and isinstance(initial_data[field_name], str):
                            field.initial = [initial_data[field_name]]  # Convert single value to list for multiple choice
                        else:
                            field.initial = initial_data[field_name]
        
        form = SingleQuestionForm(initial=initial_data)
    
    progress = int(((current_index + 1) / total_questions) * 100) if total_questions > 0 else 0
    
    return render(request, 'surveys/take_survey.html', {
        'survey': survey,
        'form': form,
        'current_question': current_question,
        'current_index': current_index + 1,  # 1-based index for display
        'total_questions': total_questions,
        'progress': progress,
        'is_last_question': current_index == total_questions - 1
    })

@login_required
def survey_complete(request, survey_id):
    """Display a thank you page after survey completion and redirect to lucky draw if eligible"""
    survey = get_object_or_404(Survey, id=survey_id)
    
    # Check if user is eligible for lucky draw
    from .lucky_draw import LuckyDrawView
    lucky_draw_view = LuckyDrawView()
    if lucky_draw_view.is_eligible(request.user):
        messages.success(request, 'Congratulations! You are now eligible for the lucky draw!')
        return redirect('surveys:lucky_draw')
    
    return render(request, 'surveys/survey_complete.html', {
        'survey': survey,
    })