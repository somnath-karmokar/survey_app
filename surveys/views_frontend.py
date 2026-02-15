from django.shortcuts import render, redirect, reverse
from django.views.generic import TemplateView, CreateView, FormView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, authenticate, get_user_model
from django.utils import timezone
from datetime import timedelta
from .models import Survey, SurveyResponse, UserProfile, LoginOTP, LuckyDrawEntry
from django.http import JsonResponse, HttpResponseRedirect
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.db import models
from django.urls import reverse_lazy

User = get_user_model()

# Add Max to the existing imports
from django.db.models import Sum, Count, F, Q, Max
from django.utils import timezone
from datetime import timedelta
from surveys.models import Country, Survey, SurveyResponse, UserProfile
from django.contrib import messages
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect
from .forms import UserRegistrationForm, UserRegisterForm

from django.contrib.auth.views import LoginView as BaseLoginView
from django.contrib.auth import authenticate, login as auth_login
from django.contrib import messages
from django.urls import reverse_lazy
from django.shortcuts import redirect, render
from django.http import HttpResponseRedirect, JsonResponse
import logging
from django.conf import settings as django_settings

# Set up logging
logger = logging.getLogger(__name__)

class CustomLoginView(BaseLoginView):
    template_name = 'frontpage/login.html'
    form_class = AuthenticationForm
    redirect_authenticated_user = False
    
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)
    
    def post(self, request, *args, **kwargs):
        logger.info('Login form submitted')
        logger.info(f'POST data: {request.POST}')
        
        # Handle OTP-based login
        email = request.POST.get('email', '').strip()
        otp_code = request.POST.get('otp_code', '').strip()
        
        if email and otp_code:
            logger.info(f'Attempting OTP authentication for email: {email}')
            
            # Authenticate using OTP backend
            user = authenticate(request, email=email, otp_code=otp_code)
            logger.info(f'OTP Authentication result: {user}')
            
            if user is not None:
                logger.info(f'User {email} authenticated successfully via OTP')
                
                # Check if user has a profile and is a frontend user
                if hasattr(user, 'profile'):
                    logger.info(f'User profile exists. user_type: {user.profile.user_type}')
                    if user.profile.user_type != 'frontend':
                        logger.warning(f'User {email} is not authorized to access frontend')
                        messages.error(
                            request,
                            'This account is not authorized to access the frontend.'
                        )
                        return JsonResponse({
                            'success': False,
                            'error': 'This account is not authorized to access the frontend.'
                        })
                else:
                    # Create profile if it doesn't exist
                    logger.info('Creating new user profile')
                    from .models import UserProfile
                    UserProfile.objects.create(user=user, user_type='frontend')
                
                # Log the user in
                from surveys.authentication import OTPBackend
                auth_login(request, user, backend='surveys.authentication.OTPBackend')
                logger.info(f'User {email} logged in successfully via OTP')
                messages.success(request, f'Welcome back, {user.username}!')
                
                # Handle AJAX response
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    next_url = request.POST.get('next') or request.GET.get('next')
                    return JsonResponse({
                        'success': True,
                        'message': 'Login successful!',
                        'redirect': next_url or reverse_lazy('surveys:dashboard')
                    })
                
                # Get the next URL from POST or GET
                next_url = request.POST.get('next') or request.GET.get('next')
                logger.info(f'Next URL: {next_url}')
                if next_url:
                    return redirect(next_url)
                return redirect(self.get_success_url())
            
            # OTP authentication failed
            logger.warning(f'OTP authentication failed for email: {email}')
            
            # Handle AJAX response
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid or expired code. Please try again.'
                })
            
            messages.error(request, 'Invalid or expired code. Please try again.')
            return self.form_invalid(self.get_form())
        
        # Fallback to traditional form validation for non-OTP requests
        form = self.get_form()
        logger.info(f'Form is valid: {form.is_valid()}')
        logger.info(f'Form errors: {form.errors if not form.is_valid() else "No errors"}')
        
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            logger.info(f'Attempting to authenticate user: {username}')
            
            user = authenticate(request, username=username, password=password)
            logger.info(f'Authentication result: {user}')
            
            if user is not None:
                logger.info(f'User {username} authenticated successfully')
                
                # Check if user has a profile and is a frontend user
                if hasattr(user, 'profile'):
                    logger.info(f'User profile exists. is_frontend_user: {getattr(user.profile, 'is_frontend_user', False)}')
                    if not user.profile.is_frontend_user:
                        logger.warning(f'User {username} is not authorized to access frontend')
                        messages.error(
                            request,
                            'This account is not authorized to access the frontend.'
                        )
                        return self.form_invalid(form)
                else:
                    # Create profile if it doesn't exist
                    logger.info('Creating new user profile')
                    from .models import UserProfile
                    UserProfile.objects.create(user=user, user_type='frontend')
                
                # Log the user in
                from surveys.authentication import EmailOnlyBackend
                auth_login(request, user, backend='surveys.authentication.EmailOnlyBackend')
                logger.info(f'User {username} logged in successfully')
                messages.success(request, f'Welcome back, {user.username}!')
                
                # Get the next URL from POST or GET
                next_url = request.POST.get('next') or request.GET.get('next')
                logger.info(f'Next URL: {next_url}')
                if next_url:
                    return redirect(next_url)
                return redirect(self.get_success_url())
            
            # Authentication failed
            logger.warning(f'Authentication failed for user: {username}')
            messages.error(request, 'Invalid username or password')
            
            # Return the form with errors
            return self.form_invalid(form)
        
        # Form is invalid
        logger.warning('Form is invalid')
        return self.form_invalid(form)
    
    def form_invalid(self, form):
        """If the form is invalid, render the invalid form."""
        logger.warning('Form is invalid')
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"{field}: {error}")
        return self.render_to_response(self.get_context_data(form=form))
    
    def get_success_url(self):
        return reverse_lazy('surveys:dashboard')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['countries'] = Country.objects.all()
        context.update({
            'next': self.request.GET.get('next', ''),
            'signup_url': reverse_lazy('surveys:signup') + f'?next={self.request.GET.get("next", "")}'
        })
        return context

class MySurveysView(LoginRequiredMixin, ListView):
    model = SurveyResponse
    template_name = 'frontend/my_surveys.html'
    context_object_name = 'completed_surveys'
    login_url = 'surveys:login'
    paginate_by = 10
    
    def get_queryset(self):
        return SurveyResponse.objects.filter(
            user=self.request.user,
            completed_at__isnull=False
        ).select_related('survey').order_by('-completed_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_page'] = 'my_surveys'
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'frontend/dashboard.html'
    login_url = 'surveys:login'
    redirect_field_name = 'next'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        # Get user profile
        try:
            profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            profile = None
        
        # Get surveys data
        completed_surveys = SurveyResponse.objects.filter(
            user=user,
            completed_at__isnull=False
        ).count()
        
        # Get available surveys
        available_surveys = Survey.objects.filter(
            is_active=True
        ).exclude(
            responses__user=user,
            responses__completed_at__isnull=False
        ).distinct().count()
        
        # Calculate points (assuming 10 points per completed survey)
        points_earned = completed_surveys * 10
        
        # Get recent activity
        recent_activity = SurveyResponse.objects.filter(
            user=user,
            completed_at__isnull=False
        ).select_related('survey').order_by('-completed_at')[:5]
        
        # Get available surveys for the user
        available_surveys_list = Survey.objects.filter(
            is_active=True
        ).exclude(
            responses__user=user,
            responses__completed_at__isnull=False
        )[:5]
        
        # Get recent survey responses
        recent_responses = SurveyResponse.objects.filter(
            user=user,
            started_at__gte=thirty_days_ago
        ).count()
        
        # Calculate earnings (placeholder - replace with actual calculation if needed)
        total_earnings = 0
        
        # Get recent surveys that the user has responded to, with response counts
        recent_surveys = Survey.objects.filter(
            responses__user=user
        ).annotate(
            response_count=Count('responses', filter=Q(responses__user=user)),
            last_response=Max('responses__started_at')
        ).order_by('-last_response')[:5]
        
        level_progress = {}
        if hasattr(user, 'survey_progress'):
            # Group by level and sum completed_count
            progress_by_level = user.survey_progress.values('level').annotate(
                total_completed=Sum('completed_count')
            )
            level_progress = {p['level']: p['total_completed'] for p in progress_by_level}
        # Check if user is eligible for lucky draw in any level
        lucky_draw_eligible = any(
            count >= getattr(django_settings, 'LUCKY_DRAW_CONFIG', {}).get('SURVEYS_REQUIRED', 3)
            for level, count in level_progress.items()
        )
        
        # Add data to context
        context.update({
            'profile': profile,
            'completed_surveys': completed_surveys,
            'available_surveys': available_surveys,
            'points_earned': points_earned,
            'recent_activity': recent_activity,
            'available_surveys_list': available_surveys_list,
            'recent_responses': recent_responses,
            'total_earnings': total_earnings,
            'recent_surveys': recent_surveys,
            'active_page': 'dashboard',
            'level_progress': level_progress,
            'lucky_draw_eligible': lucky_draw_eligible,
            'LUCKY_DRAW_CONFIG': getattr(django_settings, 'LUCKY_DRAW_CONFIG', {})
        })
        
        return context

class HomePageView(TemplateView):
    template_name = 'frontpage/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get the number of days to show winners from settings
        winners_display_days = getattr(django_settings, 'LUCKY_DRAW_CONFIG', {}).get('WINNERS_DISPLAY_DAYS', 30)
        
        # Calculate the date cutoff
        cutoff_date = timezone.now() - timedelta(days=winners_display_days)
        
        # Get recent winners within the configured period
        recent_winners = LuckyDrawEntry.objects.filter(
            is_winner=True,
            created_at__gte=cutoff_date
        ).select_related('user').order_by('-created_at')
        
        # Prepare winner data for template
        winners_data = []
        for winner in recent_winners:
            # Format name as "S. Karmokar" (capital first letter)
            full_name = winner.user.get_full_name() or winner.user.username
            name_parts = full_name.split()
            if len(name_parts) > 1:
                formatted_name = f"{name_parts[0][0].upper()}. {' '.join(name_parts[1:])}"
            else:
                formatted_name = full_name
            
            # Get country name
            country_name = ""
            if hasattr(winner.user, 'profile') and winner.user.profile.country:
                country_name = winner.user.profile.country.name
            
            # Get month name
            month_name = winner.created_at.strftime("%B")
            
            # Combine all details
            winner_details = f"{formatted_name}, {country_name}, {month_name}"
            
            winners_data.append({
                'details': winner_details,
                'name': formatted_name,
                'country': country_name,
                'month': month_name,
                'date': winner.created_at,
                'profile_picture': winner.user.profile.profile_picture.url if hasattr(winner.user, 'profile') and winner.user.profile.profile_picture else None
            })
        
        context.update({
            'recent_winners': winners_data,
            'winners_display_days': winners_display_days,
        })
        
        return context

class FeaturesPageView(TemplateView):
    template_name = 'frontpage/features.html'

class FAQPageView(TemplateView):
    template_name = 'frontpage/faq.html'

class ContactPageView(TemplateView):
    template_name = 'frontpage/contact-us.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context

    def post(self, request, *args, **kwargs):
        name = request.POST.get('name', '')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        subject = request.POST.get('subject', '')
        message = request.POST.get('message', '')
        
        # Here you can add email sending logic or database storage
        # For now, just show a success message
        messages.success(request, 'Thank you for contacting us! We will get back to you soon.')
        return redirect('surveys:contact')

# In surveys/views_frontend.py

class SignUpView(CreateView):
    form_class = UserRegisterForm
    template_name = 'frontpage/login.html'
    # success_url = reverse_lazy('surveys:login')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['country_queryset'] = Country.objects.all()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['countries'] = Country.objects.all()
        current_year = timezone.now().year
        context['current_year'] = current_year
        context['max_year'] = current_year - 16  # Minimum age 16
        return context

    def get(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()
        return self.render_to_response(
            self.get_context_data(form=form)
        )

    def post(self, request, *args, **kwargs):
        print(f"DEBUG: Registration POST request received")  # Debug
        print(f"DEBUG: POST data: {request.POST}")  # Debug
        print(f"DEBUG: FILES data: {request.FILES}")  # Debug
        
        self.object = None
        form = self.get_form()
        
        print(f"DEBUG: Form is valid: {form.is_valid()}")  # Debug
        if not form.is_valid():
            print(f"DEBUG: Form errors: {form.errors}")  # Debug
            return self.form_invalid(form)
        
        print(f"DEBUG: Form is valid, proceeding with form_valid")  # Debug
        return self.form_valid(form)

    def form_valid(self, form):
        # Save the user first
        user = form.save(commit=False)
        user.is_active = True  # Set to True for immediate activation
        user.save()
        print(f'User created: {user}')
        
        # Get the form data
        middle_name = form.cleaned_data.get('middle_name')
        city = form.cleaned_data.get('city')
        state = form.cleaned_data.get('state')
        country = form.cleaned_data.get('country')
        year_of_birth = form.cleaned_data.get('year_of_birth')
        profile_picture = form.cleaned_data.get('profile_picture')
        
        # Create or update the user profile
        profile, created = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'middle_name': middle_name,
                'city': city,
                'state': state,
                'country': country,
                'user_type': 'frontend'
            }
        )
        
        if not created:
            # Update existing profile
            profile.middle_name = middle_name
            profile.city = city
            profile.state = state
            profile.country = country
            profile.user_type = 'frontend'
        
        # Handle year of birth conversion
        if year_of_birth:
            from datetime import date
            profile.date_of_birth = date(year_of_birth, 1, 1)  # Default to January 1st
        
        # Handle profile picture upload
        if profile_picture:
            profile.profile_picture = profile_picture
        
        profile.save()
        
        # Log the user in automatically since no password is required
        from django.contrib.auth import login
        from surveys.authentication import EmailOnlyBackend
        login(self.request, user, backend='surveys.authentication.EmailOnlyBackend')
        
        messages.success(
            self.request,
            'Registration successful! Welcome to our survey platform.'
        )
        
        # Return JSON response for AJAX handling
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            print(f"DEBUG: Returning JSON response for AJAX")  # Debug
            response_data = {
                'success': True,
                'message': 'Registration successful! Welcome to our survey platform.',
                'redirect': reverse_lazy('surveys:dashboard')
            }
            print(f"DEBUG: Response data: {response_data}")  # Debug
            return JsonResponse(response_data)
        
        return redirect(reverse_lazy('surveys:dashboard'))

    def form_invalid(self, form):
        """Handle invalid form with AJAX response."""
        print(f"DEBUG: Form invalid called with errors: {form.errors}")  # Debug
        
        # Handle AJAX requests
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            errors = {}
            for field, error_list in form.errors.items():
                errors[field] = error_list
            
            error_response = {
                'success': False,
                'errors': errors,
                'error': 'Please correct the errors below and try again.'
            }
            print(f"DEBUG: Returning error response: {error_response}")  # Debug
            return JsonResponse(error_response, status=400)
        
        # Handle non-AJAX requests (fallback)
        return self.render_to_response(
            self.get_context_data(form=form)
        )


def send_otp(request):
    """Send OTP to user's email for login"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        
        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Email address is required'
            })
        
        # Check if user exists
        try:
            user = User.objects.get(
                models.Q(email=email) | models.Q(username=email)
            )
            
            # Check if user has a profile and is a frontend user
            if hasattr(user, 'profile') and user.profile.user_type == 'frontend':
                # Generate OTP
                otp = LoginOTP.generate_otp(user, email)
                print(f'OTP generated: {otp.code}')
                # Send email
                try:
                    subject = 'Your Login Code - Survey App'
                    message = f'''
                                Hello {user.first_name or user.username},

                                Your login code is: {otp.code}

                                This code will expire in 10 minutes.

                                If you didn't request this code, please ignore this email.

                                Best regards,
                                Survey App Team
                    '''
                    
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        fail_silently=False,
                    )
                    
                    return JsonResponse({
                        'success': True,
                        'message': f'Login code sent to {email}',
                        'expires_in': 600  # 10 minutes in seconds
                    })
                    
                except Exception as e:
                    return JsonResponse({
                        'success': False,
                        'error': 'Failed to send email. Please try again.'
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'User account not found or not authorized'
                })
                
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'No account found with this email address'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': 'An error occurred. Please try again.'
            })
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    })
