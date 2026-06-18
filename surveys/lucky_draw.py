import random
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic import View
from .models import (
    UserSurveyProgress, LuckyDrawEntry, PollResponse, CountryLuckyDrawConfig,
    SurveyResponse,
)
from django.db.models import Sum
import random
from django.utils import timezone
from django.http import JsonResponse  # Add this line
import json
from decimal import Decimal
from .emails import send_lucky_draw_winner_email, send_lucky_draw_winner_admin_notification


class LuckyDrawView(View):
    def get_user_country_config(self, user):
        profile = getattr(user, 'profile', None)
        country = getattr(profile, 'country', None)
        return CountryLuckyDrawConfig.get_for_country(country)

    def get_poll_requirement(self, user):
        settings_requirement = settings.LUCKY_DRAW_CONFIG.get('POLLS_REQUIRED')
        if settings_requirement is not None:
            return settings_requirement

        config = self.get_user_country_config(user)
        if config:
            return config.poll_count_required
        return 5

    def get_prize_for_user(self, user):
        config = self.get_user_country_config(user)
        if config:
            return config.get_prize_display()

        profile = getattr(user, 'profile', None)
        country_code = str(getattr(getattr(profile, 'country', None), 'code', '') or '').upper()
        if country_code in ['US', 'CA']:
            return '$1 USD'
        if country_code == 'GB':
            return '\u00a31 GBP'
        if country_code == 'NG':
            return '$0.50 USD'
        return '$1 USD'

    def get_wallet_credit_amount(self, user):
        profile = getattr(user, 'profile', None)
        country_code = str(getattr(getattr(profile, 'country', None), 'code', '') or '').upper()
        if country_code == 'NG':
            return Decimal('0.50')
        return Decimal('1.00')

    def credit_winner_wallet(self, entry):
        if not entry.is_winner:
            return Decimal('0.00')

        from django.db import transaction
        from django.db.models import F
        from .models import UserProfile, WalletTransaction

        if WalletTransaction.objects.filter(lucky_draw_entry=entry).exists():
            return Decimal('0.00')

        amount = self.get_wallet_credit_amount(entry.user)
        with transaction.atomic():
            profile, _ = UserProfile.objects.select_for_update().get_or_create(user=entry.user)
            UserProfile.objects.filter(pk=profile.pk).update(wallet_balance=F('wallet_balance') + amount)
            profile.refresh_from_db(fields=['wallet_balance'])
            WalletTransaction.objects.create(
                profile=profile,
                transaction_type=WalletTransaction.TRANSACTION_TYPE_CREDIT,
                amount=amount,
                currency_code=profile.wallet_currency_code,
                currency_symbol=profile.wallet_currency_symbol,
                description=f"{entry.get_draw_type_display()} lucky draw win",
                lucky_draw_entry=entry,
                balance_after=profile.wallet_balance,
            )
        return amount

    def get_completion_counts(self, user):
        total_surveys = user.survey_progress.aggregate(
            total=Sum('completed_count')
        )['total'] or 0
        total_polls = PollResponse.objects.filter(user=user).count()
        return total_surveys, total_polls

    def get_last_entry(self, user, draw_type):
        return user.lucky_draw_entries.filter(draw_type=draw_type).order_by('-created_at').first()

    def get_qualifying_survey(self, user, last_entry):
        queryset = SurveyResponse.objects.filter(
            user=user,
            completed_at__isnull=False,
        ).select_related('survey').order_by('-completed_at')
        if last_entry:
            queryset = queryset.filter(completed_at__gt=last_entry.created_at)
        response = queryset.first()
        return response.survey if response else None

    def get_qualifying_poll(self, user, last_entry):
        queryset = PollResponse.objects.filter(user=user).select_related('poll').order_by('-submitted_at')
        if last_entry:
            queryset = queryset.filter(submitted_at__gt=last_entry.created_at)
        response = queryset.first()
        return response.poll if response else None

    def get_eligibility_context(self, user):
        last_entry = user.lucky_draw_entries.order_by('-created_at').first()
        last_survey_entry = self.get_last_entry(user, LuckyDrawEntry.DRAW_TYPE_SURVEY)
        last_poll_entry = self.get_last_entry(user, LuckyDrawEntry.DRAW_TYPE_POLL)
        total_surveys, total_polls = self.get_completion_counts(user)
        surveys_required = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
        polls_required = self.get_poll_requirement(user)

        surveys_completed = max(0, total_surveys - (last_survey_entry.surveys_at_play or 0)) if last_survey_entry else total_surveys
        polls_completed = max(0, total_polls - (last_poll_entry.polls_at_play or 0)) if last_poll_entry else total_polls
        survey_eligible = surveys_completed >= surveys_required
        poll_eligible = polls_completed >= polls_required
        eligible_draw_types = []
        if survey_eligible:
            eligible_draw_types.append(LuckyDrawEntry.DRAW_TYPE_SURVEY)
        if poll_eligible:
            eligible_draw_types.append(LuckyDrawEntry.DRAW_TYPE_POLL)

        return {
            'last_entry': last_entry,
            'last_survey_entry': last_survey_entry,
            'last_poll_entry': last_poll_entry,
            'total_surveys': total_surveys,
            'total_polls': total_polls,
            'surveys_completed': surveys_completed,
            'polls_completed': polls_completed,
            'surveys_required': surveys_required,
            'polls_required': polls_required,
            'survey_eligible': survey_eligible,
            'poll_eligible': poll_eligible,
            'eligible_draw_types': eligible_draw_types,
            'user_eligible': bool(eligible_draw_types),
        }

    def resolve_draw_type(self, user, requested_draw_type=None):
        if requested_draw_type in {LuckyDrawEntry.DRAW_TYPE_SURVEY, LuckyDrawEntry.DRAW_TYPE_POLL}:
            return requested_draw_type

        eligible_draw_types = self.get_eligibility_context(user)['eligible_draw_types']
        if eligible_draw_types:
            return eligible_draw_types[0]
        return LuckyDrawEntry.DRAW_TYPE_SURVEY

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
        
        eligibility = self.get_eligibility_context(request.user)
        last_entry = eligibility['last_entry']
        
        # Get current month's winning number
        current_winner = LuckyDrawEntry.objects.filter(
            created_at__month=current_month,
            created_at__year=current_year,
            is_winner=True
        ).order_by('-created_at').first()
        
        total_surveys = eligibility['total_surveys']
        total_polls = eligibility['total_polls']
        surveys_completed = eligibility['surveys_completed']
        polls_completed = eligibility['polls_completed']
        surveys_required = eligibility['surveys_required']
        polls_required = eligibility['polls_required']
        user_eligible = eligibility['user_eligible']
        survey_eligible = eligibility['survey_eligible']
        poll_eligible = eligibility['poll_eligible']
        
        # Debug output
        print("\n=== Lucky Draw Debug Info ===")
        print(f"Total Surveys: {total_surveys}")
        print(f"Total Polls: {total_polls}")
        print(f"Surveys Since Last Play: {surveys_completed}")
        print(f"Polls Since Last Play: {polls_completed}")
        print(f"Surveys Required: {surveys_required}")
        print(f"Polls Required: {polls_required}")
        print(f"User Eligible: {user_eligible}")
        if last_entry:
            print(f"Last Play: {last_entry.created_at}")
            print(f"Surveys at Last Play: {last_entry.surveys_at_play}")
        print("==========================\n")
        
        # Generate number range from settings
        number_range = list(range(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END'] + 1
        ))
        random.shuffle(number_range)
        
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
            'survey_eligible': survey_eligible,
            'poll_eligible': poll_eligible,
            'eligible_draw_types': eligibility['eligible_draw_types'],
            'selected_draw_type': eligibility['eligible_draw_types'][0] if eligibility['eligible_draw_types'] else '',
            'surveys_completed': surveys_completed,
            'polls_completed': polls_completed,
            'surveys_required': surveys_required,
            'polls_required': polls_required,
            'current_lucky_number': current_lucky_number,
            'current_winner': current_winner,
            'last_play_date': last_entry.created_at if last_entry else None,
            'last_result': last_entry,
            'has_played': bool(last_entry and not user_eligible),
            'prize_display': self.get_prize_for_user(request.user),
        }
        
        return render(request, 'surveys/lucky_draw.html', context)

    def get_lucky_number(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Not authenticated'}, status=401)

        draw_type = self.resolve_draw_type(request.user, request.GET.get('draw_type'))
        # Check if user is eligible to play
        if not self.is_eligible(request.user, draw_type):
            required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
            required_polls = self.get_poll_requirement(request.user)
            return JsonResponse({
                'error': f'You need to complete {required_surveys} surveys or {required_polls} polls to play the lucky draw.'
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
            
        
        
       
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid request'}, status=400)

        requested_draw_type = data.get('draw_type')
        if requested_draw_type and requested_draw_type not in {LuckyDrawEntry.DRAW_TYPE_SURVEY, LuckyDrawEntry.DRAW_TYPE_POLL}:
            return JsonResponse({'error': 'Invalid lucky draw type.'}, status=400)
        draw_type = self.resolve_draw_type(request.user, requested_draw_type)

        # Check if user is eligible to play for the selected source.
        if not self.is_eligible(request.user, draw_type):
            required_surveys = settings.LUCKY_DRAW_CONFIG.get('SURVEYS_REQUIRED', 3)
            required_polls = self.get_poll_requirement(request.user)
            return JsonResponse({
                'error': f'You need to complete {required_surveys} surveys or {required_polls} polls to play again.'
            }, status=400)

        try:
            number = int(data.get('number'))
            if not (settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'] <= number <= settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']):
                raise ValueError('Invalid number')
        except (ValueError, TypeError) as e:
            return JsonResponse({'error': 'Invalid number'}, status=400)
        
        total_surveys, total_polls = self.get_completion_counts(request.user)
        last_entry = self.get_last_entry(request.user, draw_type)
        qualifying_survey = None
        qualifying_poll = None
        if draw_type == LuckyDrawEntry.DRAW_TYPE_SURVEY:
            qualifying_survey = self.get_qualifying_survey(request.user, last_entry)
        else:
            qualifying_poll = self.get_qualifying_poll(request.user, last_entry)
        
        # Generate winning number
        winning_number = int(data.get('current_lucky_number')) if data.get('current_lucky_number') else random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )
        
        is_winner = (number == winning_number)
        prize = self.get_prize_for_user(request.user) if is_winner else None
        
        # Create entry
        entry = LuckyDrawEntry.objects.create(
            user=request.user,
            draw_type=draw_type,
            survey=qualifying_survey,
            poll=qualifying_poll,
            guessed_number=number,
            winning_number=winning_number,
            is_winner=is_winner,
            prize=prize,
            surveys_at_play=total_surveys,
            polls_at_play=total_polls
        )
        
        # Send email notifications if user won
        if is_winner:
            self.credit_winner_wallet(entry)
            try:
                # Send winner email to user
                
                send_lucky_draw_winner_email(entry)
                send_lucky_draw_winner_admin_notification(entry)
                print(f"Winner emails sent to {entry.user.email} and admin")
            except Exception as e:
                # Log the error but don't fail the request
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to send winner emails: {str(e)}")
                print(f"Error sending winner emails: {str(e)}")
        
        return JsonResponse({
            'is_winner': is_winner,
            'winning_number': winning_number,
            'prize': prize,
            'draw_type': draw_type,
            'remaining_draw_types': [
                entry_type for entry_type in self.get_eligibility_context(request.user)['eligible_draw_types']
                if entry_type != draw_type
            ],
        })

    def is_eligible(self, user, draw_type=None):
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
        eligibility = self.get_eligibility_context(user)
        total_surveys = eligibility['total_surveys']
        total_polls = eligibility['total_polls']
        required_surveys = eligibility['surveys_required']
        required_polls = eligibility['polls_required']

        if draw_type == LuckyDrawEntry.DRAW_TYPE_SURVEY:
            return eligibility['survey_eligible']
        if draw_type == LuckyDrawEntry.DRAW_TYPE_POLL:
            return eligibility['poll_eligible']
        
        # If user has never played, check if they've completed the required surveys
        if not last_entry:
            is_eligible = eligibility['user_eligible']
            print(f"User has never played. Eligible: {is_eligible} (surveys: {total_surveys}/{required_surveys}, polls: {total_polls}/{required_polls})")
            return is_eligible
        
        # Calculate surveys completed since last play
        surveys_since_last_play = eligibility['surveys_completed']
        polls_since_last_play = eligibility['polls_completed']
        is_eligible = eligibility['user_eligible']
        
        print(f"Eligibility check:")
        print(f"- Total surveys: {total_surveys}")
        print(f"- Total polls: {total_polls}")
        print(f"- Surveys at last play: {last_entry.surveys_at_play}")
        print(f"- Polls at last play: {last_entry.polls_at_play}")
        print(f"- Surveys since last play: {surveys_since_last_play}")
        print(f"- Polls since last play: {polls_since_last_play}")
        print(f"- Required surveys: {required_surveys}")
        print(f"- Required polls: {required_polls}")
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
