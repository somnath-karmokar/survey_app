from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.db.models import Count, Q, F
from django import forms
from datetime import timedelta

from django.utils import timezone
from django.forms import inlineformset_factory
from django.http import JsonResponse
from django.conf import settings
from django.template.loader import render_to_string
from django.core.mail import send_mail, EmailMultiAlternatives
from django.utils.html import strip_tags

from .models import (
    Survey, SurveyCategory, Question, UserSurveyProgress, SurveyResponse, Answer, LuckyDrawEntry, Advertiser,
    Choice, UserProfile,
)
from .views import should_show_advertisement
from .forms import SurveyResponseForm
from .emails import send_survey_completion_email, send_lucky_draw_entry_email, send_lucky_draw_winner_email
from .milestones import check_and_award_milestones
from .survey_progress import full_survey_ids, open_survey_summary


def thank_you_message(user):
    """The survey "Thank you" flash message.

    When exactly one more survey would qualify the user for the Quick draw, that
    is added to the same message.
    """
    from .lucky_draw import LuckyDrawView
    message = 'Thank you for completing the survey!'
    nudge = LuckyDrawView().quick_draw_nudge(user)
    return f'{message} {nudge}' if nudge else message


# surveys/views_surveys.py
@login_required
def survey_list(request):
    # Get all active categories that have active surveys
    categories = SurveyCategory.objects.filter(surveys__is_active=True)

    # Filter categories by the user's country (if available)
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.country:
            categories = categories.filter(country=profile.country)

    # Randomise the display order (was alphabetical via the model's default
    # ordering). distinct() + order_by('?') cannot be combined directly here —
    # the surveys__is_active join fans out per survey, and Postgres then treats
    # each joined row as distinct once RANDOM() is involved, producing
    # duplicate categories. Resolving the distinct ids first, then re-querying
    # by id with a random order, avoids that.
    category_ids = list(categories.distinct().values_list('id', flat=True))
    categories = SurveyCategory.objects.filter(id__in=category_ids).prefetch_related('surveys').order_by('?')

    # Get all surveys the user has completed
    completed_responses = SurveyResponse.objects.filter(
        user=request.user,
        completed_at__isnull=False
    ).select_related('survey')
    
    # survey_id: latest completed_at
    completed_surveys = {}
    for response in completed_responses:
        if response.survey_id not in completed_surveys or response.completed_at > completed_surveys[response.survey_id]:
            completed_surveys[response.survey_id] = response.completed_at

    # A completed survey is closed for DEFAULT_COOLDOWN_DAYS (90): survey_id -> days left (0 = can retake).
    cooldown = timedelta(days=settings.SURVEY_CONFIG.get('DEFAULT_COOLDOWN_DAYS', 90))
    now = timezone.now()
    cooldown_days_left = {
        survey_id: max(0, (completed_at + cooldown - now).days + (1 if completed_at + cooldown > now else 0))
        for survey_id, completed_at in completed_surveys.items()
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
        'cooldown_days': settings.SURVEY_CONFIG.get('DEFAULT_COOLDOWN_DAYS', 90),
        'cooldown_days_left': cooldown_days_left,
        'now': timezone.now(),  # Add this line
        'monthly_survey_limit': SurveyResponse.monthly_limit_status(request.user),
        'open_survey': open_survey_summary(request.user),
        # surveys whose category already has all the responses it needs in this country
        'full_surveys': full_survey_ids(
            request.user, Survey.objects.filter(category__in=categories, is_active=True).select_related('category')),
    }
    return render(request, 'surveys/survey_list.html', context)

MAX_SECONDS_PER_QUESTION = 30 * 60      # timer: an idle tab can't add more than this per question


def stored_answer_initial(question, answer):
    """Form initial data for a saved Answer."""
    field_name = f'question_{question.id}'
    if answer is None:
        return {}
    if question.question_type in ('single_choice', 'multiple_choice'):
        values = [str(pk) for pk in answer.selected_choices.values_list('id', flat=True)]
        other = (answer.text_answer or '').strip()
        if other:
            values.append(SurveyResponseForm.OTHER_CHOICE_VALUE)
        value = values if question.question_type == 'multiple_choice' else (values[0] if values else None)
        return {field_name: value, f'{field_name}_other': other}
    if question.question_type == 'rating':
        return {field_name: answer.rating_value}
    return {field_name: answer.text_answer}


def save_answer(response, question, value, other_text, seconds=0):
    """Create or replace the response's answer to one question, adding the time spent on it."""
    answer, _ = Answer.objects.get_or_create(response=response, question=question)
    if answer.answered_at is None:
        answer.answered_at = timezone.now()
    answer.time_spent_seconds = (answer.time_spent_seconds or 0) + seconds
    answer.text_answer = None
    answer.rating_value = None
    if question.question_type in ('single_choice', 'multiple_choice'):
        picked = value if isinstance(value, (list, tuple)) else [value]
        answer.selected_choices.set([v for v in picked if v and str(v) != SurveyResponseForm.OTHER_CHOICE_VALUE])
        answer.text_answer = other_text or None
    elif question.question_type == 'rating':
        answer.rating_value = int(value) if value not in (None, '') else None
    else:
        answer.text_answer = '' if value is None else str(value)
    answer.save()
    return answer


def elapsed_seconds(request):
    try:
        seconds = int(float(request.POST.get('elapsed_seconds') or 0))
    except (TypeError, ValueError):
        return 0
    return max(0, min(seconds, MAX_SECONDS_PER_QUESTION))


@never_cache
@login_required
def survey_detail(request, survey_id, question_index=None):
    """One question of a survey, in parts, saving each answer as it is given.

    Answers are stored on an unfinished SurveyResponse, so the user continues
    where they left off (opening the survey goes straight to the first
    unanswered question). Questions can't be skipped, a survey in another
    category is blocked until this one is finished, and the time spent is kept.
    """
    from .survey_progress import answered_question_ids, open_response, question_parts, screening_question_ids
    survey = get_object_or_404(Survey, id=survey_id, is_active=True)

    # Suspended (untruthful screening answer): no surveys until the suspension ends.
    profile = request.user.profile
    if profile.is_suspended:
        messages.error(request, (
            f"{UserProfile.SUSPENSION_MESSAGE} You can't take surveys until "
            f"{timezone.localtime(profile.suspended_until):%d %B %Y, %H:%M}."
        ))
        return redirect('surveys:category_detail', category_slug=survey.category.slug)

    unfinished_elsewhere = open_response(request.user)
    if unfinished_elsewhere is not None and unfinished_elsewhere.survey_id != survey.id:
        messages.warning(request, (
            f"Please finish all the parts of your '{unfinished_elsewhere.survey.category.name}' survey "
            f"before starting another category. You're continuing where you left off."
        ))
        return redirect('surveys:survey_detail', survey_id=unfinished_elsewhere.survey_id)

    # Suspension, monthly cap, cooldown
    can_take, message = survey.can_user_take_survey(request.user)
    if not can_take:
        messages.warning(request, message)
        return redirect('surveys:category_detail', category_slug=survey.category.slug)

    questions = list(survey.questions.all().order_by('order', 'id'))
    total_questions = len(questions)
    if not questions:
        messages.warning(request, 'This survey has no questions yet.')
        return redirect('surveys:survey_list')

    response = open_response(request.user, survey)
    answered = answered_question_ids(response)
    first_unanswered = next((i for i, q in enumerate(questions) if q.id not in answered), total_questions - 1)

    # Opening the survey resumes it; questions can't be skipped.
    if question_index is None:
        if first_unanswered > 0:
            messages.info(request, 'Welcome back - you are continuing where you left off.')
            return redirect('surveys:survey_question', survey_id=survey.id, question_index=first_unanswered)
        question_index = 0
    question_index = max(0, min(int(question_index), total_questions - 1))
    if question_index > first_unanswered:
        return redirect('surveys:survey_question', survey_id=survey.id, question_index=first_unanswered)

    current_question = questions[question_index]
    parts = question_parts(questions, screening_question_ids(questions))
    show_ad = False

    if request.method == 'POST':
        form = SurveyResponseForm(data=request.POST, survey=survey, question_id=current_question.id)

        if form.is_valid():
            field_name = f'question_{current_question.id}'
            answer_value = form.cleaned_data.get(field_name)
            other_text = (form.cleaned_data.get(f'{field_name}_other') or '').strip()

            # An untruthful answer (e.g. a made-up brand in the screening question)
            # ends the survey on the spot: nothing is kept and the user is suspended.
            if current_question.question_type in ['single_choice', 'multiple_choice']:
                picked = answer_value if isinstance(answer_value, (list, tuple)) else [answer_value]
                picked_ids = [int(v) for v in picked if str(v).isdigit()]
                picked_choices = list(Choice.objects.filter(question=current_question, id__in=picked_ids).order_by('id'))
                untruthful = [c.choice_text for c in picked_choices if c.is_disqualifying]
                if untruthful:
                    if response is not None:
                        response.delete()
                    request.session.pop(f'survey_{survey_id}_answers', None)
                    selected = [c.choice_text for c in picked_choices]
                    if other_text:
                        selected.append(f'{other_text} (typed in)')
                    request.user.profile.suspend_for_untruthful_answer(
                        survey=survey, question=current_question, selected=selected, untruthful=untruthful,
                    )
                    messages.error(request, UserProfile.SUSPENSION_MESSAGE)
                    return redirect('surveys:user_profile')

            if response is None:
                response = SurveyResponse.objects.create(user=request.user, survey=survey)
            seconds = elapsed_seconds(request)
            save_answer(response, current_question, answer_value, other_text, seconds)
            SurveyResponse.objects.filter(pk=response.pk).update(
                time_spent_seconds=F('time_spent_seconds') + seconds,
            )
            response.refresh_from_db(fields=['time_spent_seconds'])
            answered.add(current_question.id)

            # A commercial after every AD_FREQUENCY (5) questions: after Q5, Q10, Q15 ...
            # Counted on the main questions (the screening question isn't one), never on the last.
            ad_frequency = max(1, int(getattr(settings, 'SURVEY_CONFIG', {}).get('AD_FREQUENCY', 5)))
            question_number = sum(1 for p in parts[:question_index + 1] if p)
            ad_shown_key = f'survey_{survey_id}_ad_shown_q{question_index}'
            if (parts[question_index] and question_number % ad_frequency == 0
                    and question_index < total_questions - 1 and not request.session.get(ad_shown_key)):
                request.session[ad_shown_key] = True
                show_ad = True
            else:
                request.session.pop(ad_shown_key, None)
                next_index = next((i for i, q in enumerate(questions) if q.id not in answered), None)
                if next_index is None:
                    return finish_survey(request, survey, response)
                # Going back and re-answering moves on to the next question, not the first gap.
                if question_index + 1 < total_questions and question_index + 1 <= next_index:
                    next_index = question_index + 1
                return redirect('surveys:survey_question', survey_id=survey.id, question_index=next_index)
        else:
            messages.error(request, 'Please correct the highlighted answer before continuing.')
    else:
        initial_data = {}
        if response is not None and current_question.id in answered:
            initial_data = stored_answer_initial(
                current_question, response.answers.filter(question=current_question).first(),
            )
        form = SurveyResponseForm(survey=survey, question_id=current_question.id, initial=initial_data)

    return render(request, 'surveys/survey_detail.html', survey_page_context(
        request, survey, response, questions, parts, question_index, form, show_ad,
    ))


def survey_page_context(request, survey, response, questions, parts, question_index, form, show_ad):
    from .lucky_draw import LuckyDrawView
    from .survey_progress import survey_part_count
    total_questions = len(questions)
    part = parts[question_index]
    in_part = [i for i, p in enumerate(parts) if p == part]
    answered_count = response.answers.count() if response is not None else 0
    parts_total = survey_part_count()
    return {
        'survey': survey,
        'form': form,
        'current_question': questions[question_index],
        'question_index': question_index,
        'total_questions': total_questions,
        'progress': int(answered_count / total_questions * 100) if total_questions else 0,
        'is_last_question': question_index == total_questions - 1,
        'show_ad': show_ad,
        'advertiser': Advertiser.pick_for(survey, request.user) if show_ad else None,
        'part': part,                                   # 0 = screening question
        'parts_total': parts_total,
        'part_range': range(1, parts_total + 1),
        'part_question_number': (in_part.index(question_index) + 1) if part else 0,
        'part_question_total': len(in_part),
        'question_number': sum(1 for p in parts[:question_index + 1] if p),
        'time_spent_seconds': response.time_spent_seconds if response is not None else 0,
        'quick_draw': LuckyDrawView().quick_draw_progress(request.user),
        # The screening step has its own layout and needs the bound fields directly.
        'screening_field': form[f'question_{questions[question_index].id}'] if part == 0 else None,
        'screening_other_field': (
            form[f'question_{questions[question_index].id}_other']
            if part == 0 and f'question_{questions[question_index].id}_other' in form.fields else None
        ),
    }


def finish_survey(request, survey, response):
    """All questions answered: mark the survey complete and count it (one per category)."""
    updated = SurveyResponse.objects.filter(pk=response.pk, completed_at__isnull=True).update(
        completed_at=timezone.now(),
    )
    if updated:
        progress, created = UserSurveyProgress.objects.get_or_create(
            user=request.user, category=survey.category, level=survey.level,
            defaults={'completed_count': 1},
        )
        if not created:
            progress.completed_count = F('completed_count') + 1
            progress.save(update_fields=['completed_count', 'last_completed'])
        check_and_award_milestones(request.user)
        from .rewards import credit_category_completion
        response.refresh_from_db()
        reward = credit_category_completion(response)
        message = thank_you_message(request.user)
        if reward is not None:
            message = (f'{message} {reward.amount_display} has been added to your wallet '
                       f'for completing the {survey.category.name} category.')
        messages.success(request, message)
    request.session.pop(f'survey_{survey.id}_answers', None)
    return redirect('surveys:survey_complete', survey_id=survey.id)


@login_required
def lucky_draw_entry(request):
    """Handle lucky draw number selection"""
    current_month = timezone.now().month
    current_year = timezone.now().year
    
    # Check if user has completed all surveys for the current month
    active_surveys = Survey.objects.filter(
        is_active=True
    )
    
    completed_surveys = SurveyResponse.objects.filter(
        user=request.user,
        completed_at__month=current_month,
        completed_at__year=current_year
    ).values_list('survey_id', flat=True)
    
    all_surveys_completed = all(survey.id in completed_surveys for survey in active_surveys)
    
    if not all_surveys_completed and active_surveys.exists():
        messages.warning(request, 'Please complete all surveys before entering the lucky draw.')
        return redirect('survey_list')
    
    # Check if user has already entered the lucky draw this month
    existing_entry = LuckyDrawEntry.objects.filter(
        user=request.user,
        month=current_month,
        year=current_year
    ).first()
    
    if request.method == 'POST':
        if existing_entry:
            messages.info(request, 'You have already entered the lucky draw for this month.')
            return redirect('survey_list')
            
        selected_number = request.POST.get('selected_number')
        
        if not selected_number or not selected_number.isdigit():
            messages.error(request, 'Please select a valid number.')
        else:
            selected_number = int(selected_number)
            if selected_number < 1 or selected_number > 100:
                messages.error(request, 'Please select a number between 1 and 100.')
            else:
                # Check if the number is already taken this month
                if LuckyDrawEntry.objects.filter(
                    month=current_month,
                    year=current_year,
                    selected_number=selected_number
                ).exists():
                    messages.error(request, 'This number has already been selected. Please choose another one.')
                else:
                    # Create new lucky draw entry
                    entry = LuckyDrawEntry.objects.create(
                        user=request.user,
                        selected_number=selected_number,
                        month=current_month,
                        year=current_year,
                        is_winner=False
                    )
                    
                    # Send lucky draw entry confirmation email
                    try:
                        send_lucky_draw_entry_email(request.user, entry)
                    except Exception as e:
                        # Log the error but don't show it to the user
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.error(f"Failed to send lucky draw email: {str(e)}")
                    
                    messages.success(request, f'Your lucky number {selected_number} has been entered into the draw! A confirmation has been sent to your email.')
                    return redirect('surveys:survey_list')
    
    # Get previous winners for display
    previous_winners = LuckyDrawEntry.objects.filter(
        is_winner=True
    ).order_by('-year', '-month')[:10]  # Show last 10 winners
    
    context = {
        'already_participated': existing_entry is not None,
        'existing_entry': existing_entry,
        'previous_winners': previous_winners,
    }
    
    if existing_entry:
        context['existing_entry'] = existing_entry
    
    return render(request, 'surveys/lucky_draw.html', context)

@login_required
def take_survey(request, survey_id, question_id=None):
    """Old survey URL (/surveys/take/<id>/): the survey is taken in parts on survey_detail,
    which also resumes where the user left off."""
    return redirect('surveys:survey_detail', survey_id=survey_id)


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
