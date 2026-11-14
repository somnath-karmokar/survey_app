from decimal import Decimal
from django.shortcuts import render, redirect, reverse, get_object_or_404
from django.views.generic import TemplateView, CreateView, FormView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login, authenticate, get_user_model
from django.utils import timezone
from datetime import timedelta
from .models import (
    Survey, SurveyCategory, SurveyResponse, UserProfile, LoginOTP, LuckyDrawEntry,
    Poll, PollResponse, WalletTransaction, WalletWithdrawalRequest, Question, PollQuestion,
    JournalPost, JournalCategory, PrivacyPolicy, AboutUs, DirectMarketing, Advertiser
)
from .milestones import get_survey_milestone_progress
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
from surveys.models import Country, Survey, SurveyCategory, SurveyResponse, UserProfile
from django.contrib import messages
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView
from django.http import HttpResponseRedirect
from .forms import UserRegistrationForm, UserRegisterForm, PollResponseForm, WalletWithdrawalRequestForm

from django.contrib.auth.views import LoginView as BaseLoginView
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.contrib import messages
from django.urls import reverse_lazy
from django.shortcuts import redirect, render
from django.http import HttpResponseRedirect, JsonResponse
import logging
from django.conf import settings as django_settings
from .emails import send_withdrawal_request_admin_notification

# Set up logging
logger = logging.getLogger(__name__)


class SearchView(TemplateView):
    """Site search (the search box in the header).

    Finds site pages (Lucky draw, Withdraw, FAQ...), survey categories, surveys,
    polls and - for logged-in users - survey and poll questions. Logged-in users
    see their own country's content; visitors see each category once.
    A query matches when the whole phrase appears, or when every significant
    word appears ("draw winners", "cinema survey"). Question matches are grouped
    into one result per survey or poll ("12 questions mention ...").
    """
    template_name = 'surveys/search_results.html'
    min_query_length = 2
    result_limit = 12
    # Words too common to narrow a search on their own.
    STOP_WORDS = {
        'a', 'an', 'and', 'are', 'at', 'can', 'do', 'for', 'how', 'i', 'in', 'is', 'it', 'me', 'my',
        'of', 'on', 'or', 'the', 'to', 'what', 'where', 'with', 'you', 'your',
        'survey', 'surveys', 'poll', 'polls', 'page', 'sudraw',
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = ' '.join(self.request.GET.get('q', '').split())[:100]
        results = []

        # Searches made only of very common words ("the", "how to") would match everything.
        if len(query) >= self.min_query_length and self.query_words(query):
            if self.request.user.is_authenticated:
                results = self.get_search_results(query)
            else:
                results = self.get_public_search_results(query)

        context.update({
            'query': query,
            'results': results,
            'result_count': len(results),
            'min_query_length': self.min_query_length,
            'can_view_results': self.request.user.is_authenticated,
        })
        return context

    # ── matching ──────────────────────────────────────────────────────────────

    def query_words(self, query):
        words = [w for w in query.lower().replace(',', ' ').split() if len(w) > 1]
        return [w for w in words if w not in self.STOP_WORDS]

    def text_filter(self, query, fields):
        """Q: the phrase in any field, or every significant word in some field."""
        phrase = Q()
        for field in fields:
            phrase |= Q(**{f'{field}__icontains': query})
        words = self.query_words(query)
        if words == [query.lower()]:
            return phrase
        all_words = Q()
        for word in words:
            any_field = Q()
            for field in fields:
                any_field |= Q(**{f'{field}__icontains': word})
            all_words &= any_field
        return phrase | all_words

    def text_matches(self, query, text):
        words = self.query_words(query)
        if not words:
            return False
        text = (text or '').lower()
        return query.lower() in text or all(word in text for word in words)

    # ── results ───────────────────────────────────────────────────────────────

    def category_results(self, query, country=None):
        """One result per category name (visitors would otherwise see one per country)."""
        categories = SurveyCategory.objects.filter(self.text_filter(query, ('name', 'description')))
        if country is not None:
            categories = categories.filter(country=country)
        results, seen = [], set()
        for category in categories.order_by('order', 'name', 'id'):
            key = category.name.strip().lower()
            if key in seen or not category.slug:
                continue
            seen.add(key)
            results.append({
                'type': 'Category',
                'title': category.name,
                'description': category.description or '',
                'url': reverse('surveys:category_detail', kwargs={'category_slug': category.slug}),
            })
            if len(results) >= self.result_limit:
                break
        return results

    def poll_results(self, query, country=None):
        polls = Poll.objects.filter(self.text_filter(query, ('title', 'description')), is_active=True)
        if country is not None:
            polls = polls.filter(country=country)
        results, seen = [], set()
        for poll in polls.select_related('country').order_by('order', '-created_at'):
            key = poll.title.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            results.append({
                'type': 'Poll',
                'title': poll.title,
                'description': poll.description or str(poll.country or ''),
                'url': reverse('surveys:poll_detail', kwargs={'poll_id': poll.id}),
            })
            if len(results) >= self.result_limit:
                break
        return results

    def get_public_search_results(self, query):
        results = self.get_static_page_results(query)
        results += self.category_results(query)
        results += self.poll_results(query)
        return results[:50]

    def get_search_results(self, query):
        country = self.get_user_country()
        results = self.get_static_page_results(query)
        categories = self.category_results(query, country)
        results += categories
        listed = {r['title'].strip().lower(): r for r in categories}

        # Surveys matched by name, or by questions that mention the search words.
        surveys = Survey.objects.filter(is_active=True).select_related('category')
        if country is not None:
            surveys = surveys.filter(category__country=country)
        by_name = surveys.filter(self.text_filter(query, ('name', 'description', 'category__name')))
        question_hits = dict(
            Question.objects.filter(self.text_filter(query, ('question_text', 'topic')),
                                    surveys__in=surveys)
            .values('surveys').annotate(n=Count('id', distinct=True)).values_list('surveys', 'n')
        )
        matched = {s.id: s for s in by_name}
        matched.update({s.id: s for s in surveys.filter(id__in=question_hits)})
        for survey in sorted(matched.values(), key=lambda s: (-question_hits.get(s.id, 0), s.category.name)):
            hits = question_hits.get(survey.id, 0)
            hits_text = f'{hits} question{"s mention" if hits != 1 else " mentions"} "{query}"'
            category_result = listed.get(survey.category.name.strip().lower())
            if category_result is not None:
                # Already shown as its category (same page): add the question count there.
                if hits:
                    category_result['description'] = hits_text
                continue
            results.append({
                'type': 'Survey',
                'title': f'{survey.category.name} survey',
                'description': hits_text if hits else (survey.description or survey.category.name),
                'url': reverse('surveys:category_detail', kwargs={'category_slug': survey.category.slug})
                if survey.category.slug else reverse('surveys:survey_detail', kwargs={'survey_id': survey.id}),
            })
            if len(results) >= 40:
                break

        polls = self.poll_results(query, country)
        listed_polls = {r['url'] for r in polls}
        results += polls
        poll_hits = (
            PollQuestion.objects.filter(self.text_filter(query, ('question_text',)), poll__is_active=True)
            .filter(**({'poll__country': country} if country is not None else {}))
            .values('poll_id', 'poll__title').annotate(n=Count('id')).order_by('-n')[:self.result_limit]
        )
        for hit in poll_hits:
            url = reverse('surveys:poll_detail', kwargs={'poll_id': hit['poll_id']})
            if url in listed_polls:
                continue
            results.append({
                'type': 'Poll',
                'title': hit['poll__title'],
                'description': f'{hit["n"]} question{"s mention" if hit["n"] != 1 else " mentions"} "{query}"',
                'url': url,
            })
        return results[:50]

    def get_user_country(self):
        if not self.request.user.is_authenticated:
            return None

        profile = getattr(self.request.user, 'profile', None)
        return getattr(profile, 'country', None)

    def get_static_page_results(self, query):
        """Site pages, found by their title, description or keywords."""
        pages = (
            ('Survey Categories', 'Browse the survey categories available in your country.', 'surveys:category_list',
             'categories category browse take start begin questionnaire'),
            ('Lucky Draw', 'Play the Quick draw: one play for every 30 survey questions you answer.', 'surveys:lucky_draw',
             'lucky draw quick draw prize prizes win winner winners play number game'),
            ('Polls', 'Answer quick polls and earn Poll draw plays.', 'surveys:poll_list',
             'polls poll vote voting opinion'),
            ('Withdraw', 'Withdraw your wallet balance to your bank, PayPal or a verifiable charity '
             '(we add 20% to charity donations).', 'surveys:wallet_withdrawal_request',
             'withdraw withdrawal cash out payout payment pay bank paypal charity donate donation money gift card'),
            ('Wallet', 'Your wallet balance and transaction history.', 'surveys:wallet_history',
             'wallet balance transactions history earnings money credit rewards reward'),
            ('Dashboard', 'Your surveys, rewards and draws at a glance.', 'surveys:dashboard',
             'dashboard account overview my progress'),
            ('Profile', 'Your account details and settings.', 'surveys:user_profile',
             'profile account details settings password email suspension suspended'),
            ('FAQ', 'Answers about surveys, draws, rewards, withdrawals, charity donations and your account.',
             'surveys:faq', 'faq help question questions answers how rules terms conditions eligibility '
             'withdraw withdrawal charity donate prize prizes winners draw rewards privacy account'),
            ('Features', 'What Sudraw offers.', 'surveys:features', 'features platform about how it works'),
            ('About Us', 'Who we are.', 'surveys:about_us', 'about us company who team sudraw'),
            ('Privacy Policy', 'How we collect and use your data.', 'surveys:privacy_policy',
             'privacy policy data gdpr personal information cookies'),
            ('Contact Us', 'Get in touch with the Sudraw team.', 'surveys:contact',
             'contact support email help complaint problem error'),
            ('Home', 'Sudraw surveys, polls, rewards and prize draws.', 'surveys:home',
             'home homepage sudraw main start'),
        )
        results = []
        for title, description, url_name, keywords in pages:
            if self.text_matches(query, f'{title} {description} {keywords}'):
                results.append({'type': 'Page', 'title': title, 'description': description, 'url': reverse(url_name)})
        return results[:5]


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
                
                # Check if email is verified
                if hasattr(user, 'profile') and not user.profile.email_verified:
                    logger.warning(f'User {email} email is not verified')
                    messages.error(request, 'Please verify your email before logging in.')
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'success': False,
                            'error': 'Please verify your email before logging in.',
                            'redirect': reverse_lazy('surveys:pending_verification')
                        })
                    return self.form_invalid(self.get_form())
                
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
                        'redirect': next_url or self.get_success_url()
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
                
                # Check if email is verified
                if hasattr(user, 'profile') and not user.profile.email_verified:
                    logger.warning(f'User {username} email is not verified')
                    messages.error(request, 'Please verify your email before logging in.')
                    return redirect(reverse_lazy('surveys:pending_verification'))
                
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
        """Back into an unfinished survey if there is one (it resumes where they left off), else the dashboard."""
        user = self.request.user
        if user.is_authenticated:
            from .survey_progress import open_response
            profile = getattr(user, 'profile', None)
            unfinished = open_response(user)
            if unfinished is not None and not (profile and profile.is_suspended):
                messages.info(self.request, (
                    f"You're continuing your {unfinished.survey.category.name} survey where you left off."
                ))
                return reverse_lazy('surveys:survey_detail', kwargs={'survey_id': unfinished.survey_id})
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
        ).select_related('survey', 'survey__category').order_by('-completed_at')
    
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
        profile, _ = UserProfile.objects.get_or_create(user=user)
        
        # Get surveys data
        completed_surveys = SurveyResponse.objects.filter(
            user=user,
            completed_at__isnull=False
        ).count()
        
        # Get available surveys
        available_surveys = Survey.objects.filter(
            is_active=True,
            category__country_id=profile.country_id if profile and profile.country_id else None
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
            is_active=True,
            category__country_id=profile.country_id if profile and profile.country_id else None
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
        from .lucky_draw import LuckyDrawView
        lucky_draw_view = LuckyDrawView()
        lucky_draw_eligible = lucky_draw_view.is_eligible(user)
        monthly_draw_stats = lucky_draw_view.get_monthly_profile_stats(user)

        # None when the surveys-completed milestone doesn't apply to this
        # user (e.g. Nigeria, or no country set) - the template hides the
        # progress card entirely in that case.
        survey_milestone = get_survey_milestone_progress(user)

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
            'wallet_balance_display': profile.wallet_display,
            'recent_wallet_transactions': profile.wallet_transactions.all()[:3],
            'active_page': 'dashboard',
            'level_progress': level_progress,
            'lucky_draw_eligible': lucky_draw_eligible,
            'LUCKY_DRAW_CONFIG': getattr(django_settings, 'LUCKY_DRAW_CONFIG', {}),
            'survey_milestone': survey_milestone,
            'monthly_draw_stats': monthly_draw_stats,
        })

        from .survey_progress import open_survey_summary
        context['open_survey'] = open_survey_summary(user)

        # Wallet credit for every completed survey (Country settings -> Category completion reward).
        from .milestones import get_wallet_reward_display
        from .rewards import category_completion_reward
        reward = category_completion_reward(profile)
        if reward > 0:
            amount, _, symbol = get_wallet_reward_display(user, reward)
            context['survey_reward'] = {'amount': amount, 'currency_symbol': symbol}
        context['suspended_until'] = profile.suspended_until if profile.is_suspended else None
        context['suspension_message'] = UserProfile.SUSPENSION_MESSAGE
        return context


class WalletTransactionHistoryView(LoginRequiredMixin, ListView):
    model = WalletTransaction
    template_name = 'frontend/wallet_history.html'
    context_object_name = 'transactions'
    login_url = 'surveys:login'
    paginate_by = 20

    def get_queryset(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return profile.wallet_transactions.select_related('lucky_draw_entry')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        from .lucky_draw import LuckyDrawView
        context.update({
            'profile': profile,
            'wallet_balance_display': profile.wallet_display,
            'withdrawal_requests': profile.withdrawal_requests.select_related('wallet_transaction')[:8],
            'active_page': 'wallet',
            'lucky_draw_eligible': LuckyDrawView().is_eligible(self.request.user),
        })
        return context


class WalletWithdrawalRequestView(LoginRequiredMixin, CreateView):
    model = WalletWithdrawalRequest
    form_class = WalletWithdrawalRequestForm
    template_name = 'frontend/wallet_withdrawal_form.html'
    login_url = 'surveys:login'

    # Users can only withdraw once their wallet reaches 10 (in their wallet currency).
    MINIMUM_WITHDRAWAL_BALANCE = Decimal('10.00')

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        profile = self.get_profile()
        if profile.wallet_balance < self.MINIMUM_WITHDRAWAL_BALANCE:
            symbol = profile.wallet_currency_symbol
            messages.warning(
                request,
                f'You need at least {symbol}{self.MINIMUM_WITHDRAWAL_BALANCE:.2f} in your wallet to request a withdrawal. '
                f'Your current balance is {profile.wallet_display}.'
            )
            return redirect(reverse_lazy('surveys:wallet_history'))
        return super().dispatch(request, *args, **kwargs)

    def get_profile(self):
        if not hasattr(self, '_profile'):
            self._profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        return self._profile

    def _is_first_withdrawal(self):
        return not WalletWithdrawalRequest.objects.filter(profile=self.get_profile()).exists()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['profile'] = self.get_profile()
        kwargs['is_first_withdrawal'] = self._is_first_withdrawal()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = self.get_profile()
        from .lucky_draw import LuckyDrawView
        context.update({
            'profile': profile,
            'wallet_balance_display': profile.wallet_display,
            'is_first_withdrawal': self._is_first_withdrawal(),
            'country_code_map': {
                str(country.pk): str(country.code).upper()
                for country in Country.objects.filter(is_active=True)
            },
            'active_page': 'wallet',
            'lucky_draw_eligible': LuckyDrawView().is_eligible(self.request.user),
        })
        from .models import Charity, charity_bonus_percent
        percent = charity_bonus_percent()
        bonus_on_ten = (Decimal('10') * percent / Decimal('100')).quantize(Decimal('0.01'))
        context.update({
            'charity_available': Charity.objects.filter(is_active=True).exists(),
            'charity_bonus_percent': (int(percent) if percent == int(percent) else percent),
            'charity_example_bonus': f'{bonus_on_ten:.2f}',
            'charity_example_total': f'{Decimal("10") + bonus_on_ten:.2f}',
        })
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        try:
            send_withdrawal_request_admin_notification(self.object)
        except Exception:
            logger.exception('Failed to send withdrawal request admin email for request %s', self.object.pk)
        if self.object.is_donation:
            messages.success(self.request, (
                f'Thank you! Your donation of {self.object.amount_display} to {self.object.charity} has been '
                f'submitted. Sudraw adds {self.object.charity_bonus_display}, so the charity will receive '
                f'{self.object.charity_total_display} once it is approved.'
            ))
        else:
            messages.success(self.request, 'Your withdrawal request has been submitted for admin approval.')
        return response

    def get_success_url(self):
        return reverse_lazy('surveys:wallet_history')


class HomePageView(TemplateView):
    template_name = 'frontpage/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import charity_bonus_percent
        percent = charity_bonus_percent()
        context['charity_bonus_percent'] = int(percent) if percent == int(percent) else percent

        categories = SurveyCategory.objects.filter(
            surveys__is_active=True,
            country__is_active=True,
        ).distinct()

        if self.request.user.is_authenticated:
            profile = getattr(self.request.user, 'profile', None)
            if profile and profile.country_id:
                categories = categories.filter(country_id=profile.country_id)

        context['featured_categories'] = categories.order_by('?')[:6]

        polls = Poll.objects.filter(
            is_active=True,
            country__is_active=True,
            questions__isnull=False,
        ).select_related('country').prefetch_related('questions').distinct()

        if self.request.user.is_authenticated:
            profile = getattr(self.request.user, 'profile', None)
            if profile and profile.country_id:
                polls = polls.filter(country_id=profile.country_id)
            else:
                polls = polls.none()

            context['featured_polls'] = polls.order_by('order', '-created_at')[:4]
        else:
            context['featured_polls'] = polls.order_by('?')[:5]
        
        # Get the number of most recent winners to show from settings
        winners_display_count = getattr(django_settings, 'LUCKY_DRAW_CONFIG', {}).get('WINNERS_DISPLAY_COUNT', 50)

        # Get the most recent winners, regardless of when they won
        recent_winners = LuckyDrawEntry.objects.filter(
            is_winner=True
        ).select_related('user').order_by('-created_at')[:winners_display_count]
        
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
            
            # Get city, state, and country name
            city_name = ""
            if hasattr(winner.user, 'profile') and winner.user.profile.city:
                city_name = winner.user.profile.city

            state_name = ""
            if hasattr(winner.user, 'profile') and winner.user.profile.state:
                state_name = winner.user.profile.state

            country_name = ""
            if hasattr(winner.user, 'profile') and winner.user.profile.country:
                country_name = winner.user.profile.country.name

            # Get month name
            month_name = winner.created_at.strftime("%B")

            # Combine all details, skipping any missing fields
            winner_details = ", ".join(
                part for part in [formatted_name, city_name, state_name, country_name, month_name] if part
            )

            winners_data.append({
                'details': winner_details,
                'name': formatted_name,
                'city': city_name,
                'state': state_name,
                'country': country_name,
                'month': month_name,
                'date': winner.created_at,
                'profile_picture': winner.user.profile.profile_picture.url if hasattr(winner.user, 'profile') and winner.user.profile.profile_picture else None
            })
        
        context.update({
            'recent_winners': winners_data,
            'winners_display_count': winners_display_count,
            # Randomised on every load, so the slider order differs each visit.
            'direct_marketing_ads': DirectMarketing.slides_for(self.request.user),
        })

        return context


@login_required(login_url='surveys:login')
def poll_list(request):
    profile = getattr(request.user, 'profile', None)
    polls = Poll.objects.filter(
        is_active=True,
        country__is_active=True,
        questions__isnull=False,
    ).select_related('country').prefetch_related('questions').distinct()

    if profile and profile.country_id:
        polls = polls.filter(country_id=profile.country_id)
    else:
        polls = polls.none()

    completed_poll_ids = set(
        PollResponse.objects.filter(user=request.user)
        .values_list('poll_id', flat=True)
    )

    poll_data = [
        {
            'poll': poll,
            'completed': poll.id in completed_poll_ids,
            'question_count': poll.questions.count(),
        }
        for poll in polls.order_by('order', '-created_at')
    ]

    return render(request, 'surveys/poll_list.html', {
        'poll_data': poll_data,
        'active_page': 'polls',
    })


def _get_available_poll_or_redirect(request, poll_id):
    poll = get_object_or_404(
        Poll.objects.select_related('country').prefetch_related('questions__choices'),
        id=poll_id,
        is_active=True,
        country__is_active=True
    )

    if not poll.is_available_for_user(request.user):
        messages.warning(request, 'This poll is not available for your country.')
        return None, redirect('surveys:home')

    if not poll.questions.exists():
        messages.warning(request, 'This poll has no questions yet.')
        return None, redirect('surveys:home')

    return poll, None


@login_required(login_url='surveys:login')
def poll_detail(request, poll_id):
    poll, redirect_response = _get_available_poll_or_redirect(request, poll_id)
    if redirect_response:
        return redirect_response

    completed = PollResponse.objects.filter(user=request.user, poll=poll).exists()

    return render(request, 'surveys/poll_landing.html', {
        'poll': poll,
        'completed': completed,
        'total_questions': poll.questions.count(),
    })


@never_cache
@login_required(login_url='surveys:login')
def poll_question(request, poll_id, question_index=0):
    poll, redirect_response = _get_available_poll_or_redirect(request, poll_id)
    if redirect_response:
        return redirect_response

    if PollResponse.objects.filter(user=request.user, poll=poll).exists():
        messages.info(request, 'You have already participated in this poll.')
        return redirect('surveys:poll_detail', poll_id=poll.id)

    questions = list(poll.questions.all().order_by('order', 'id'))
    total_questions = len(questions)
    question_index = max(0, min(int(question_index), total_questions - 1))
    current_question = questions[question_index]
    session_key = f'poll_{poll.id}_answers'

    if request.method == 'POST':
        form = PollResponseForm(request.POST, poll=poll, question_id=current_question.id)
        if form.is_valid():
            field_name = f'poll_question_{current_question.id}'
            answer_value = form.cleaned_data.get(field_name)
            answers = request.session.get(session_key, {})

            if current_question.question_type == 'multiple_choice':
                answers[str(current_question.id)] = [str(choice.id) for choice in answer_value]
            elif current_question.question_type == 'single_choice':
                answers[str(current_question.id)] = str(answer_value.id) if answer_value else ''
            else:
                answers[str(current_question.id)] = answer_value

            request.session[session_key] = answers
            request.session.save()

            # Same ad gate as surveys: after every AD_FREQUENCY questions, but
            # never on the first or last question, and only once per question.
            ad_frequency = getattr(django_settings, 'SURVEY_CONFIG', {}).get('AD_FREQUENCY', 4)
            ad_shown_key = f'poll_{poll.id}_ad_shown_q{question_index}'
            ad_already_shown = request.session.get(ad_shown_key, False)

            if (question_index > 0
                    and (question_index + 1) % ad_frequency == 0
                    and question_index < total_questions - 1
                    and not ad_already_shown):
                request.session[ad_shown_key] = True
                request.session.save()
                return render(request, 'surveys/poll_detail.html', {
                    'poll': poll,
                    'form': form,
                    'current_question': current_question,
                    'question_index': question_index,
                    'total_questions': total_questions,
                    'progress': int(((question_index + 1) / total_questions) * 100),
                    'is_last_question': question_index == total_questions - 1,
                    'show_ad': True,
                    'advertiser': Advertiser.pick_for(None, request.user),
                })

            next_index = question_index + 1
            if next_index < total_questions:
                # Clear the ad flag for this question when moving on.
                request.session.pop(ad_shown_key, None)
                return redirect('surveys:poll_question', poll_id=poll.id, question_index=next_index)

            final_form = PollResponseForm(poll=poll, data=_poll_answers_to_post_data(poll, answers))
            if final_form.is_valid():
                final_form.save(request.user, poll)
                if session_key in request.session:
                    del request.session[session_key]
                messages.success(request, 'Thank you for participating in the poll!')
                from .lucky_draw import LuckyDrawView
                if LuckyDrawView().is_eligible(request.user, LuckyDrawEntry.DRAW_TYPE_POLL):
                    messages.success(request, 'Congratulations! You are now eligible for the lucky draw!')
                    return redirect('surveys:lucky_draw')
                return render(request, 'surveys/survey_complete.html', {
                    'poll': poll,
                })

            form = final_form
    else:
        initial = {}
        saved_answer = request.session.get(session_key, {}).get(str(current_question.id))
        if saved_answer is not None:
            initial[f'poll_question_{current_question.id}'] = saved_answer
        form = PollResponseForm(poll=poll, question_id=current_question.id, initial=initial)

    return render(request, 'surveys/poll_detail.html', {
        'poll': poll,
        'form': form,
        'current_question': current_question,
        'question_index': question_index,
        'total_questions': total_questions,
        'progress': int(((question_index + 1) / total_questions) * 100),
        'is_last_question': question_index == total_questions - 1,
    })


def _poll_answers_to_post_data(poll, answers):
    from django.http import QueryDict

    data = QueryDict('', mutable=True)
    for question in poll.questions.all().order_by('order', 'id'):
        field_name = f'poll_question_{question.id}'
        answer_value = answers.get(str(question.id))
        if question.question_type == 'multiple_choice':
            data.setlist(field_name, answer_value or [])
        elif answer_value is not None:
            data[field_name] = str(answer_value)
    return data

class FeaturesPageView(TemplateView):
    template_name = 'frontpage/features.html'


class JournalListView(ListView):
    model = JournalPost
    template_name = 'surveys/journal_list.html'
    context_object_name = 'journal_posts'
    paginate_by = 9

    def get_queryset(self):
        queryset = JournalPost.objects.filter(is_published=True).order_by('-published_at')
        category_slug = self.request.GET.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category_slug = self.request.GET.get('category')
        context['categories'] = JournalCategory.objects.filter(
            journal_posts__is_published=True
        ).annotate(
            post_count=models.Count('journal_posts', filter=models.Q(journal_posts__is_published=True))
        ).distinct().order_by('name')
        context['selected_category'] = category_slug
        return context


class JournalDetailView(DetailView):
    model = JournalPost
    template_name = 'surveys/journal_detail.html'
    context_object_name = 'journal_post'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return JournalPost.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = JournalCategory.objects.filter(
            journal_posts__is_published=True
        ).annotate(
            post_count=models.Count('journal_posts', filter=models.Q(journal_posts__is_published=True))
        ).distinct().order_by('name')
        return context


class FAQPageView(TemplateView):
    template_name = 'frontpage/faq.html'


class PrivacyPolicyView(TemplateView):
    template_name = 'frontpage/privacy-policy.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['privacy_policy'] = PrivacyPolicy.objects.first()
        return context


class AboutUsView(TemplateView):
    template_name = 'frontpage/about-us.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['about_us'] = AboutUs.objects.first()
        return context

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
        user.is_active = False  # Set to False until email is verified
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
                'user_type': 'frontend',
                'email_verified': False
            }
        )
        
        if not created:
            # Update existing profile
            profile.middle_name = middle_name
            profile.city = city
            profile.state = state
            profile.country = country
            profile.user_type = 'frontend'
            profile.email_verified = False
        
        # Handle year of birth conversion
        if year_of_birth:
            from datetime import date
            profile.date_of_birth = date(year_of_birth, 1, 1)  # Default to January 1st
        
        # Handle profile picture upload
        if profile_picture:
            profile.profile_picture = profile_picture
        
        profile.save()
        
        # Generate email verification token
        from .models import EmailVerification
        email_verification = EmailVerification.generate_token(user, user.email)
        
        # Send verification email
        self.send_verification_email(user, email_verification)
        
        messages.success(
            self.request,
            f'Registration successful! Check your email ({user.email}) to verify your account.'
        )
        
        # Return JSON response for AJAX handling
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            print(f"DEBUG: Returning JSON response for AJAX")  # Debug
            response_data = {
                'success': True,
                'message': f'Registration successful! Check your email ({user.email}) to verify your account.',
                'redirect': reverse_lazy('surveys:pending_verification')
            }
            print(f"DEBUG: Response data: {response_data}")  # Debug
            return JsonResponse(response_data)
        
        return redirect(reverse_lazy('surveys:pending_verification'))

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
    
    def send_verification_email(self, user, email_verification):
        """Send email verification link to the user"""
        try:
            verification_url = self.request.build_absolute_uri(
                reverse_lazy('surveys:verify_email', kwargs={'token': email_verification.token})
            )
            
            subject = 'Verify Your Email - Sudraw'
            message = f'''
Hello {user.first_name or user.username},

Thank you for registering with Sudraw! 

Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create this account, please ignore this email.

Best regards,
Sudraw Team
            '''
            
            html_message = f'''
<html>
<body>
<p>Hello {user.first_name or user.username},</p>
<p>Thank you for registering with Sudraw!</p>
<p>Please verify your email address by clicking the link below:</p>
<p><a href="{verification_url}">Verify Email</a></p>
<p>This link will expire in 24 hours.</p>
<p>If you didn't create this account, please ignore this email.</p>
<p>Best regards,<br/>Sudraw Team</p>
</body>
</html>
            '''
            
            print(f'DEBUG: Sending verification email to {user.email} with token {email_verification.token}')
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f'Verification email sent to {user.email}')
            
        except Exception as e:
            logger.error(f'Failed to send verification email to {user.email}: {e}')
            print(f'ERROR: Failed to send verification email: {e}')



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
                    subject = 'Your Login Code - Sudraw'
                    message = f'''
                                Hello {user.first_name or user.username},

                                Your login code is: {otp.code}

                                This code will expire in 10 minutes.

                                If you didn't request this code, please ignore this email.

                                Best regards,
                                Sudraw Team
                    '''
                    print(f'DEBUG: Sending email to {email} with OTP code {otp.code} ..from  {settings.DEFAULT_FROM_EMAIL}')  # Debug
                    
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
                        'error': f'Failed to send email. Please try again--------> {e}'
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


class VerifyEmailView(TemplateView):
    """
    View to verify user's email with token
    """
    template_name = 'frontpage/verify_email.html'
    
    def get(self, request, *args, **kwargs):
        token = kwargs.get('token')
        
        if not token:
            messages.error(request, 'Invalid verification link.')
            return redirect('surveys:login')
        
        try:
            from .models import EmailVerification
            email_verification = EmailVerification.objects.get(token=token)
            
            if email_verification.verify():
                messages.success(
                    request,
                    'Email verified successfully! You can now log in to your account.'
                )
                return redirect('surveys:login')
            else:
                messages.error(
                    request,
                    'This verification link has expired or already been used. Please sign up again.'
                )
                return redirect('surveys:signup')
        
        except EmailVerification.DoesNotExist:
            messages.error(request, 'Invalid verification link.')
            return redirect('surveys:login')
        except Exception as e:
            logger.error(f'Error verifying email: {e}')
            messages.error(request, 'An error occurred while verifying your email.')
            return redirect('surveys:login')


class PendingVerificationView(TemplateView):
    """
    View to show pending email verification status
    """
    template_name = 'frontpage/pending_verification.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context
    
    def post(self, request, *args, **kwargs):
        """Resend verification email"""
        email = request.POST.get('email', '').strip()
        
        if not email:
            messages.error(request, 'Please provide your email address.')
            return self.get(request, *args, **kwargs)
        
        try:
            user = User.objects.get(email=email)
            
            if hasattr(user, 'profile') and user.profile.email_verified:
                messages.info(request, 'Your email is already verified. You can now log in.')
                return redirect('surveys:login')
            
            # Generate new verification token
            from .models import EmailVerification
            email_verification = EmailVerification.generate_token(user, user.email)
            
            # Send verification email (reuse SignUpView method)
            verification_url = request.build_absolute_uri(
                reverse_lazy('surveys:verify_email', kwargs={'token': email_verification.token})
            )
            
            subject = 'Verify Your Email - Sudraw'
            message = f'''
Hello {user.first_name or user.username},

Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create this account, please ignore this email.

Best regards,
Sudraw Team
            '''
            
            html_message = f'''
<html>
<body>
<p>Hello {user.first_name or user.username},</p>
<p>Please verify your email address by clicking the link below:</p>
<p><a href="{verification_url}">Verify Email</a></p>
<p>This link will expire in 24 hours.</p>
<p>If you didn't create this account, please ignore this email.</p>
<p>Best regards,<br/>Sudraw Team</p>
</body>
</html>
            '''
            
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            messages.success(request, f'Verification email resent to {email}. Please check your inbox.')
            return self.get(request, *args, **kwargs)
        
        except User.DoesNotExist:
            messages.error(request, 'No account found with this email address.')
            return self.get(request, *args, **kwargs)
        except Exception as e:
            logger.error(f'Error resending verification email: {e}')
            messages.error(request, 'An error occurred while resending the verification email.')
            return self.get(request, *args, **kwargs)
