import random
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic import View
from .models import UserSurveyProgress, LuckyDrawEntry
from django.db.models import Sum
import random
from django.utils import timezone
from django.http import JsonResponse  # Add this line
import json


class LuckyDrawView(View):
    def get(self, request, *args, **kwargs):
        # Check if this is a request for the lucky number
        if request.path.endswith('/number/'):
            return self.get_lucky_number(request)
        
        # Get current month and year for play check
        current_date = timezone.now()
        current_month = current_date.month
        current_year = current_date.year
        
        # Check if user has already played this month
        has_played = LuckyDrawEntry.objects.filter(
            user=request.user,
            created_at__month=current_month,
            created_at__year=current_year
        ).exists()
        
        # Get the last entry if it exists
        last_entry = request.user.lucky_draw_entries.order_by('-created_at').first()
        
        # Get current month's winning number
        current_winner = LuckyDrawEntry.objects.filter(
            created_at__month=current_month,
            created_at__year=current_year,
            is_winner=True
        ).order_by('-created_at').first()
        
        # Calculate total surveys completed
        total_surveys = request.user.survey_progress.aggregate(
            total=Sum('completed_count')
        )['total'] or 0
        
        # Calculate surveys completed since last play
        if last_entry:
            surveys_completed = max(0, total_surveys - (last_entry.surveys_at_play or 0))
        else:
            surveys_completed = total_surveys
            
        # Get required surveys from settings
        surveys_required = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
        
        # User is eligible if they've completed the required surveys since last play
        user_eligible = surveys_completed >= surveys_required
        
        # Debug output
        print("\n=== Lucky Draw Debug Info ===")
        print(f"Total Surveys: {total_surveys}")
        print(f"Surveys Since Last Play: {surveys_completed}")
        print(f"Surveys Required: {surveys_required}")
        print(f"User Eligible: {user_eligible}")
        if last_entry:
            print(f"Last Play: {last_entry.created_at}")
            print(f"Surveys at Last Play: {last_entry.surveys_at_play}")
        print("==========================\n")
        
        # Generate number range from settings
        number_range = range(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END'] + 1
        )
        
        # Generate or get current lucky number
        current_lucky_number = random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )
        
        context = {
            'LUCKY_DRAW_CONFIG': {
                **settings.LUCKY_DRAW_CONFIG,
                'NUMBER_RANGE': number_range
            },
            'user_eligible': user_eligible,
            'surveys_completed': surveys_completed,
            'surveys_required': surveys_required,
            'current_lucky_number': current_lucky_number,
            'current_winner': current_winner,
            'last_play_date': last_entry.created_at if last_entry else None,
            'last_result': last_entry
        }
        
        return render(request, 'surveys/lucky_draw.html', context)

    def get_lucky_number(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Not authenticated'}, status=401)
        
        # Check if user has already played this month
        current_month = timezone.now().month
        current_year = timezone.now().year
        has_played = LuckyDrawEntry.objects.filter(
            user=request.user,
            created_at__month=current_month,
            created_at__year=current_year
        ).exists()
        
        if has_played:
            return JsonResponse({'error': 'You have already played this month. Please complete more surveys to play again next month.'}, status=400)
        
        # Check if user is eligible to play
        if not self.is_eligible(request.user):
            required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
            return JsonResponse({
                'error': f'You need to complete {required_surveys} surveys to play the lucky draw.'
            }, status=400)
        
        # Generate a new lucky number
        lucky_number = random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )
        
        return JsonResponse({'lucky_number': lucky_number})

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Not authenticated'}, status=401)
            
        
        
       
        # Check if user is eligible to play
        if not self.is_eligible(request.user):
            required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
            return JsonResponse({
                'error': f'You need to complete {required_surveys} surveys to play again.'
            }, status=400)

        try:
            # Parse JSON data
            data = json.loads(request.body)
            number = int(data.get('number'))
            if not (settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'] <= number <= settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']):
                raise ValueError('Invalid number')
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return JsonResponse({'error': 'Invalid number'}, status=400)
        
        # Get total surveys completed
        total_surveys = request.user.survey_progress.aggregate(
            total=Sum('completed_count')
        )['total'] or 0
        
        # Generate winning number
        winning_number = random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )
        
        is_winner = (number == winning_number)
        prize = random.choice(settings.LUCKY_DRAW_CONFIG['PRIZES']) if is_winner else None
        
        # Create entry (signal will handle any notification for winners)
        entry = LuckyDrawEntry.objects.create(
            user=request.user,
            guessed_number=number,
            winning_number=winning_number,
            is_winner=is_winner,
            prize=prize,
            surveys_at_play=total_surveys
        )
        
        return JsonResponse({
            'is_winner': is_winner,
            'winning_number': winning_number,
            'prize': prize
        })

    def is_eligible(self, user):
        """
        Check if the user is eligible to play the lucky draw.
        A user is eligible if they have completed the required number of surveys
        since their last play (or since they started if they've never played).
        """
        if not user.is_authenticated:
            print("User not authenticated")
            return False
        
        # Get the last entry if it exists
        last_entry = user.lucky_draw_entries.order_by('-created_at').first()
        
        # Get total surveys completed
        total_surveys = user.survey_progress.aggregate(
            total=Sum('completed_count')
        )['total'] or 0
        
        # Get required surveys from settings
        required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
        
        # If user has never played, check if they've completed the required surveys
        if not last_entry:
            is_eligible = total_surveys >= required_surveys
            print(f"User has never played. Eligible: {is_eligible} (total_surveys: {total_surveys} >= required: {required_surveys})")
            return is_eligible
        
        # Calculate surveys completed since last play
        surveys_since_last_play = total_surveys - (last_entry.surveys_at_play or 0)
        is_eligible = surveys_since_last_play >= required_surveys
        
        print(f"Eligibility check:")
        print(f"- Total surveys: {total_surveys}")
        print(f"- Surveys at last play: {last_entry.surveys_at_play}")
        print(f"- Surveys since last play: {surveys_since_last_play}")
        print(f"- Required surveys: {required_surveys}")
        print(f"- Is eligible: {is_eligible}")
        
        return is_eligible

    @classmethod
    def update_survey_progress(cls, survey, user):
        from django.db.models import F
        
        # Get or create user's progress for this category and level
        progress, created = UserSurveyProgress.objects.get_or_create(
            user=user,
            category=survey.category,
            level=survey.level,
            defaults={'completed_count': 1}
        )
        
        if not created:
            # Use F() to prevent race conditions
            progress.completed_count = F('completed_count') + 1
            progress.save(update_fields=['completed_count', 'last_completed'])
            progress.refresh_from_db()  # Get the updated count