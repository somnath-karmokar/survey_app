from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from ckeditor.fields import RichTextField
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

def category_image_upload_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/category_images/<category_id>/<filename>
    return f'category_images/{instance.id}/{filename}'

class Country(models.Model):
    """Represents a country where surveys can be conducted."""
    name = models.CharField(max_length=100, unique=True, help_text="Name of the country")
    code = CountryField(unique=True, help_text="ISO 3166-1 alpha-2 country code (e.g., US, GB, IN)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = _('Country')
        verbose_name_plural = _('Countries')
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

        
class SurveyCategory(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, blank=True, help_text='A URL-friendly version of the name. Will be automatically generated from the name.')
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='categories', help_text='The country this category belongs to')
    # Keeping region for backward compatibility
    region = property(lambda self: self.country)
    description = RichTextField(blank=True, null=True, help_text='Category description (supports rich text)')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    image = models.ImageField(upload_to=category_image_upload_path, blank=True, null=True)
    order = models.PositiveIntegerField(default=0, help_text='Categories will be ordered by this value in ascending order')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    @classmethod
    def make_slug(cls, name, instance=None):
        """Generate a unique slug from the name."""
        slug = slugify(name)
        original_slug = slug
        counter = 1
        
        # Check for existing slugs, excluding the current instance if updating
        while cls.objects.filter(slug=slug).exclude(pk=getattr(instance, 'pk', None)).exists():
            slug = f"{original_slug}-{counter}"
            counter += 1
            
        return slug
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.__class__.make_slug(self.name, self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Survey Categories"
        ordering = ['order', 'name']  # Order by order number, then by name




class Survey(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    category = models.ForeignKey(
        'SurveyCategory', 
        on_delete=models.CASCADE, 
        related_name='surveys'
    )
    level = models.PositiveSmallIntegerField(
        default=1,
        validators=[
            MinValueValidator(1, message='Level must be at least 1'),
            MaxValueValidator(10, message='Level cannot be greater than 10')
        ],
        help_text='Difficulty level of the survey (1-10)'
    )

    def __str__(self):
        return f"{self.name} ({self.category.name})"

    def save(self, *args, **kwargs):
        # Allow multiple active surveys
        super().save(*args, **kwargs)

    @property
    def cooldown_days(self):
        """Get the cooldown period from settings, with a default of 60 days."""
        return getattr(settings, 'SURVEY_CONFIG', {}).get('DEFAULT_COOLDOWN_DAYS', 60)

    def get_sequence_lock_info(self, user):
        """
        Lock a survey until every earlier survey in the category sequence
        (ordered by level, then id) has been completed by the user.

        Two conditions lock a survey:
        1. A previous survey has fewer (or equal) completions than this one
           — the user hasn't done the prerequisite enough times yet.
        2. A previous survey's cooldown has expired (it is due for retake)
           — strict chronological order must be maintained every cycle, so the
           user must retake the earlier level before continuing to later ones.
        """
        if not user.is_authenticated:
            return False, None

        ordered_survey_ids = list(
            Survey.objects.filter(
                category=self.category,
                is_active=True,
            ).order_by('level', 'id').values_list('id', flat=True)
        )

        try:
            current_index = ordered_survey_ids.index(self.id)
        except ValueError:
            return False, None

        if current_index == 0:
            return False, None

        previous_survey_ids = ordered_survey_ids[:current_index]

        # Single query: get completion count AND last completion timestamp per survey
        completion_info = {
            item['survey_id']: {
                'count': item['count'],
                'last_at': item['last_at'],
            }
            for item in SurveyResponse.objects.filter(
                user=user,
                survey_id__in=ordered_survey_ids,
                completed_at__isnull=False,
            ).values('survey_id').annotate(
                count=models.Count('id'),
                last_at=models.Max('completed_at'),
            )
        }

        current_completion_count = completion_info.get(self.id, {}).get('count', 0)
        cooldown_days = self.cooldown_days
        now = timezone.now()

        for previous_survey_id in previous_survey_ids:
            prev_info = completion_info.get(previous_survey_id, {})
            previous_completion_count = prev_info.get('count', 0)

            # Condition 1: previous level not done enough times relative to current
            if previous_completion_count <= current_completion_count:
                previous_survey = Survey.objects.filter(id=previous_survey_id).only('name', 'level').first()
                if previous_survey:
                    if current_completion_count > 0:
                        return True, f"Retake '{previous_survey.name}' (Level {previous_survey.level}) first"
                    return True, f"Complete '{previous_survey.name}' (Level {previous_survey.level}) to unlock"
                if current_completion_count > 0:
                    return True, "Retake the previous survey first"
                return True, "Complete the previous survey to unlock"

            # Condition 2: previous level cooldown has expired — it is due for retake.
            # The user must follow strict chronological order (L1 → L2 → L3 every cycle),
            # so when L1 becomes retakeable, L2 (and all later levels) must wait.
            last_at = prev_info.get('last_at')
            if last_at and now >= last_at + timedelta(days=cooldown_days):
                previous_survey = Survey.objects.filter(id=previous_survey_id).only('name', 'level').first()
                if previous_survey:
                    return True, f"Retake '{previous_survey.name}' (Level {previous_survey.level}) first to continue"
                return True, "Retake the previous survey first to continue"

        return False, None

    def get_level_lock_info(self, user):
        """Backward-compatible wrapper for sequence-based locking."""
        return self.get_sequence_lock_info(user)
    
    def can_user_take_survey(self, user):
        """Check if the user can take this survey based on level order and cooldown."""
        if not user.is_authenticated:
            return False, "You must be logged in to take this survey."

        is_sequence_locked, sequence_lock_message = self.get_sequence_lock_info(user)
        if is_sequence_locked:
            return False, sequence_lock_message
        
        # Check if user has already completed this specific survey
        last_response = SurveyResponse.objects.filter(
            user=user,
            survey=self,
            completed_at__isnull=False
        ).order_by('-completed_at').first()
        
        if last_response and last_response.completed_at:
            cooldown_until = last_response.completed_at + timedelta(days=self.cooldown_days)
            if timezone.now() < cooldown_until:
                days_left = (cooldown_until - timezone.now()).days + 1
                return False, (
                    f"You've already completed the survey '{self.name}'. "
                    f"Please wait {days_left} more days before taking this survey again."
                )
        return True, None

    def is_locked_for_user(self, user):
        """Check if this survey is locked for the user based on level order or cooldown."""
        if not user.is_authenticated:
            return False, "You must be logged in to take this survey."

        is_sequence_locked, sequence_lock_message = self.get_sequence_lock_info(user)
        if is_sequence_locked:
            return True, sequence_lock_message
            
        # Check if user has completed this specific survey
        last_response = SurveyResponse.objects.filter(
            user=user,
            survey=self,
            completed_at__isnull=False
        ).order_by('-completed_at').first()
        
        if last_response and last_response.completed_at:
            cooldown_until = last_response.completed_at + timedelta(days=self.cooldown_days)
            if timezone.now() < cooldown_until:
                days_left = (cooldown_until - timezone.now()).days + 1
                return True, (
                    f"You've already completed the survey '{self.name}'. "
                    f"Please wait {days_left} more days before taking this survey again."
                )
        return False, None

class Question(models.Model):
    QUESTION_TYPES = (
        ('text', 'Text Answer'),
        ('single_choice', 'Single Choice'),
        ('multiple_choice', 'Multiple Choice'),
        ('rating', 'Rating (1-5)'),
    )
    surveys = models.ManyToManyField(Survey, related_name='questions', blank=True)
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.question_text[:50]}..."

class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    choice_text = models.CharField(max_length=200)
    
    def __str__(self):
        return self.choice_text

class SurveyResponse(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='survey_responses')
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='responses')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.user.username}'s response to {self.survey.name}"
    
    def save(self, *args, **kwargs):
        # Set completed_at to now if this is a new response being completed
        if self.completed_at is None and 'completed' in kwargs:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)
        
    @property
    def time_spent(self):
        """
        Calculate the time spent on the survey in minutes.
        Returns 'Not completed' if the survey is still in progress.
        """
        if not self.completed_at:
            return "In progress"
            
        duration = self.completed_at - self.started_at
        total_seconds = int(duration.total_seconds())
        
        # Format as HH:MM:SS
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Survey Response'
        verbose_name_plural = 'Survey Responses'

class Answer(models.Model):
    response = models.ForeignKey(SurveyResponse, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    text_answer = models.TextField(blank=True, null=True)
    selected_choices = models.ManyToManyField(Choice, blank=True)
    rating_value = models.PositiveSmallIntegerField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    
    def __str__(self):
        return f"Answer to '{self.question.question_text[:30]}...' by {self.response.user.username}"


class Poll(models.Model):
    """Country-specific poll displayed on the public home page."""
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='polls')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.country.name})"

    def is_available_for_user(self, user):
        if not user.is_authenticated:
            return True

        profile = getattr(user, 'profile', None)
        if profile and profile.country_id:
            return profile.country_id == self.country_id

        return False


class PollQuestion(models.Model):
    QUESTION_TYPES = (
        ('text', 'Text Answer'),
        ('single_choice', 'Single Choice'),
        ('multiple_choice', 'Multiple Choice'),
        ('rating', 'Rating (1-5)'),
    )
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.question_text[:50]}..."


class PollChoice(models.Model):
    question = models.ForeignKey(PollQuestion, on_delete=models.CASCADE, related_name='choices')
    choice_text = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.choice_text


class PollResponse(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='poll_responses')
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='responses')
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']
        unique_together = ('user', 'poll')

    def __str__(self):
        return f"{self.user.username}'s response to {self.poll.title}"


class PollAnswer(models.Model):
    response = models.ForeignKey(PollResponse, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(PollQuestion, on_delete=models.CASCADE)
    text_answer = models.TextField(blank=True, null=True)
    selected_choices = models.ManyToManyField(PollChoice, blank=True)
    rating_value = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    def __str__(self):
        return f"Answer to '{self.question.question_text[:30]}...' by {self.response.user.username}"


class CountryLuckyDrawConfig(models.Model):
    """Country-specific lucky draw reward and poll eligibility settings."""
    country = models.OneToOneField(Country, on_delete=models.CASCADE, related_name='lucky_draw_config')
    poll_count_required = models.PositiveIntegerField(default=5)
    prize_amount = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    currency_symbol = models.CharField(max_length=5, default='$')
    currency_code = models.CharField(max_length=10, default='USD')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Country Lucky Draw Config'
        verbose_name_plural = 'Country Lucky Draw Configs'

    def __str__(self):
        return f"{self.country.name}: {self.get_prize_display()} every {self.poll_count_required} polls"

    def get_prize_display(self):
        amount = int(self.prize_amount) if self.prize_amount == self.prize_amount.to_integral() else f"{self.prize_amount:.2f}"
        return f"{self.currency_symbol}{amount} {self.currency_code}".strip()

    @classmethod
    def get_for_country(cls, country):
        if country:
            config = cls.objects.filter(country=country, is_active=True).first()
            if config:
                return config
        return None


class LuckyDrawEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lucky_draw_entries')
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    selected_number = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ('user', 'month', 'year')
        verbose_name_plural = 'Lucky Draw Entries'
    
    def __str__(self):
        return f"{self.user.username}'s entry for {self.month}/{self.year} - Number: {self.selected_number}"


class UserType(models.Model):
    """Model to store different types of users."""
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.name

class UserProfile(models.Model):
    """Extended user profile information."""
    USER_TYPE_CHOICES = [
        ('admin', 'Admin'),
        ('frontend', 'Frontend User'),
        ('staff', 'Staff'),
        ('api', 'API User'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    user_type = models.CharField(
        max_length=20, 
        choices=USER_TYPE_CHOICES, 
        default='frontend',
        help_text='Type of user account'
    )
    middle_name = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.ForeignKey(
        Country, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    postal_code = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    email_verified = models.BooleanField(default=False)
    last_login_ip = models.GenericIPAddressField(blank=True, null=True)
    last_login_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Profile ({self.get_user_type_display()})"
        
    @property
    def is_frontend_user(self):
        return self.user_type == 'frontend'

    @property
    def wallet_currency_code(self):
        country_code = str(getattr(getattr(self, 'country', None), 'code', '') or '').upper()
        if country_code == 'GB':
            return 'GBP'
        return 'USD'

    @property
    def wallet_currency_symbol(self):
        country_code = str(getattr(getattr(self, 'country', None), 'code', '') or '').upper()
        if country_code == 'GB':
            return '\u00a3'
        return '$'

    @property
    def wallet_display(self):
        amount = self.wallet_balance or Decimal('0.00')
        return f"{self.wallet_currency_symbol}{amount:.2f} {self.wallet_currency_code}"

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'


class UserWallet(UserProfile):
    class Meta:
        proxy = True
        verbose_name = 'User Wallet Detail'
        verbose_name_plural = 'User Wallet Details'
        ordering = ['user__username']


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """Create or update the user profile when a User is saved."""
    if created:
        UserProfile.objects.create(user=instance)
    # For existing users, just save the profile
    instance.profile.save()


class UserSurveyProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='survey_progress')
    category = models.ForeignKey(SurveyCategory, on_delete=models.CASCADE)
    level = models.PositiveSmallIntegerField()
    completed_count = models.PositiveIntegerField(default=0)
    last_completed = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = ('user', 'category', 'level')
        verbose_name_plural = 'User Survey Progress'
    def __str__(self):
        return f"{self.user.username} - {self.category.name} (Level {self.level}): {self.completed_count}"
# In models.py, update the LuckyDrawEntry model:
class LuckyDrawEntry(models.Model):
    DRAW_TYPE_SURVEY = 'survey'
    DRAW_TYPE_POLL = 'poll'
    DRAW_TYPE_CHOICES = [
        (DRAW_TYPE_SURVEY, 'Survey'),
        (DRAW_TYPE_POLL, 'Poll'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lucky_draw_entries')
    created_at = models.DateTimeField(auto_now_add=True)
    draw_type = models.CharField(
        max_length=10,
        choices=DRAW_TYPE_CHOICES,
        default=DRAW_TYPE_SURVEY,
        db_index=True,
        help_text="Whether this lucky draw play was earned from surveys or polls.",
    )
    survey = models.ForeignKey(
        Survey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lucky_draw_entries',
        help_text="Survey that qualified this lucky draw play, when applicable.",
    )
    poll = models.ForeignKey(
        Poll,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lucky_draw_entries',
        help_text="Poll that qualified this lucky draw play, when applicable.",
    )
    is_winner = models.BooleanField(default=False)
    guessed_number = models.PositiveIntegerField()
    winning_number = models.PositiveIntegerField()
    prize = models.CharField(max_length=100, blank=True, null=True)
    surveys_at_play = models.PositiveIntegerField(help_text="Total surveys completed when this entry was created")
    polls_at_play = models.PositiveIntegerField(default=0, help_text="Total polls completed when this entry was created")

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Lucky Draw Entries'

    def __str__(self):
        return f"{self.user} - {self.get_draw_type_display()} lucky draw on {self.created_at:%Y-%m-%d}"

    @property
    def source_object(self):
        if self.draw_type == self.DRAW_TYPE_POLL:
            return self.poll
        return self.survey


class WalletTransaction(models.Model):
    TRANSACTION_TYPE_CREDIT = 'credit'
    TRANSACTION_TYPE_DEBIT = 'debit'
    TRANSACTION_TYPE_CHOICES = [
        (TRANSACTION_TYPE_CREDIT, 'Credit'),
        (TRANSACTION_TYPE_DEBIT, 'Debit'),
    ]

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='wallet_transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency_code = models.CharField(max_length=10, default='USD')
    currency_symbol = models.CharField(max_length=5, default='$')
    description = models.CharField(max_length=255)
    lucky_draw_entry = models.OneToOneField(
        LuckyDrawEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_transaction',
    )
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Wallet Transaction'
        verbose_name_plural = 'Wallet Transactions'

    def __str__(self):
        return f"{self.profile.user.username} {self.get_transaction_type_display()} {self.amount_display}"

    @property
    def amount_display(self):
        return f"{self.currency_symbol}{self.amount:.2f} {self.currency_code}"

    @property
    def balance_after_display(self):
        return f"{self.currency_symbol}{self.balance_after:.2f} {self.currency_code}"


class WalletWithdrawalRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    PAYMENT_METHOD_PAYPAL = 'paypal'
    PAYMENT_METHOD_BANK = 'bank_transfer'
    PAYMENT_METHOD_GIFT_CARD = 'gift_card'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_PAYPAL, 'PayPal'),
        (PAYMENT_METHOD_BANK, 'Direct Bank Transfer'),
        (PAYMENT_METHOD_GIFT_CARD, 'Gift Card'),
    ]

    profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='withdrawal_requests')
    full_name = models.CharField(max_length=160, help_text='Name as it appears on the payment account.')
    email = models.EmailField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    currency_code = models.CharField(max_length=10, default='USD')
    currency_symbol = models.CharField(max_length=5, default='$')
    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    paypal_email = models.EmailField(blank=True)
    bank_account_name = models.CharField(max_length=160, blank=True)
    bank_name = models.CharField(max_length=160, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)
    routing_number = models.CharField(max_length=32, blank=True)
    sort_code = models.CharField(max_length=32, blank=True)
    iban = models.CharField(max_length=64, blank=True)
    nuban_number = models.CharField(max_length=32, blank=True, verbose_name='NUBAN account number')
    transit_number = models.CharField(max_length=32, blank=True)
    institution_number = models.CharField(max_length=32, blank=True)
    gift_card_brand = models.CharField(max_length=80, blank=True)
    gift_card_email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    admin_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_withdrawal_requests',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    wallet_transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='withdrawal_request',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Wallet Withdrawal Request'
        verbose_name_plural = 'Wallet Withdrawal Requests'

    def __str__(self):
        return f"{self.profile.user.username} withdrawal {self.amount_display} ({self.get_status_display()})"

    @property
    def amount_display(self):
        return f"{self.currency_symbol}{self.amount:.2f} {self.currency_code}"

    @property
    def country_code(self):
        return str(getattr(getattr(self, 'country', None), 'code', '') or '').upper()

    @property
    def local_identifier_name(self):
        return {
            'GB': 'Sort Code / IBAN',
            'US': 'Routing Number',
            'NG': 'NUBAN',
            'CA': 'EFT Details',
        }.get(self.country_code, 'Bank Identifier')

    def send_status_notification(self, action_label):
        try:
            from .emails import send_withdrawal_request_status_email
            send_withdrawal_request_status_email(self)
        except Exception:
            logger.exception(
                'Failed to send withdrawal %s email for request %s',
                action_label,
                self.pk,
            )

    def approve(self, reviewed_by=None):
        if self.status != self.STATUS_PENDING:
            raise ValidationError('Only pending withdrawal requests can be approved.')

        with transaction.atomic():
            profile = UserProfile.objects.select_for_update().get(pk=self.profile_id)
            if profile.wallet_balance < self.amount:
                raise ValidationError('Insufficient wallet balance for this withdrawal.')

            profile.wallet_balance = profile.wallet_balance - self.amount
            profile.save(update_fields=['wallet_balance', 'updated_at'])

            wallet_transaction = WalletTransaction.objects.create(
                profile=profile,
                transaction_type=WalletTransaction.TRANSACTION_TYPE_DEBIT,
                amount=self.amount,
                currency_code=self.currency_code,
                currency_symbol=self.currency_symbol,
                description=f"Withdrawal approved via {self.get_payment_method_display()}",
                balance_after=profile.wallet_balance,
            )

            self.status = self.STATUS_APPROVED
            self.reviewed_by = reviewed_by
            self.reviewed_at = timezone.now()
            self.wallet_transaction = wallet_transaction
            self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'wallet_transaction', 'updated_at'])
            transaction.on_commit(lambda: self.send_status_notification('approval'))

    def reject(self, reviewed_by=None):
        if self.status != self.STATUS_PENDING:
            raise ValidationError('Only pending withdrawal requests can be rejected.')
        self.status = self.STATUS_REJECTED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
        self.send_status_notification('rejection')


class LoginOTP(models.Model):
    """
    Model to store one-time passwords for email-based login
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_otps')
    email = models.EmailField()
    code = models.CharField(max_length=6)  # 6-digit code
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)

    def __str__(self):
        return f"OTP for {self.email} - {self.code}"

    @classmethod
    def generate_otp(cls, user, email):
        """Generate a new OTP for the user"""
        import random
        import string
        
        # Invalidate any existing OTPs for this user
        cls.objects.filter(user=user, is_used=False).update(is_used=True)
        
        # Generate 6-digit code
        code = ''.join(random.choices(string.digits, k=6))
        
        # Set expiry time (10 minutes from now)
        expires_at = timezone.now() + timezone.timedelta(minutes=10)
        
        return cls.objects.create(
            user=user,
            email=email,
            code=code,
            expires_at=expires_at
        )

    def is_valid(self):
        """Check if OTP is valid (not expired, not used, and attempts not exceeded)"""
        return (
            not self.is_used and 
            timezone.now() < self.expires_at and 
            self.attempts < self.max_attempts
        )

    def verify(self, entered_code):
        """Verify the entered OTP code"""
        if not self.is_valid():
            return False
        
        self.attempts += 1
        self.save()
        
        if self.code == entered_code:
            self.is_used = True
            self.save()
            return True
        
        return False

    class Meta:
        verbose_name = "Login OTP"
        verbose_name_plural = "Login OTPs"
        ordering = ['-created_at']


class EmailVerification(models.Model):
    """
    Model to store email verification tokens for new user registrations
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Email verification for {self.email}"

    @classmethod
    def generate_token(cls, user, email):
        """Generate a new verification token for the user"""
        import uuid
        
        # Delete any existing unverified tokens for this user
        cls.objects.filter(user=user, is_verified=False).delete()
        
        # Generate token
        token = str(uuid.uuid4()).replace('-', '')
        
        # Set expiry time (24 hours from now)
        expires_at = timezone.now() + timezone.timedelta(hours=24)
        
        return cls.objects.create(
            user=user,
            email=email,
            token=token,
            expires_at=expires_at
        )

    def is_valid(self):
        """Check if token is valid (not expired and not verified)"""
        return (
            not self.is_verified and 
            timezone.now() < self.expires_at
        )

    def verify(self):
        """Mark the email as verified"""
        if not self.is_valid():
            return False
        
        self.is_verified = True
        self.verified_at = timezone.now()
        self.save()
        
        # Update user profile
        if hasattr(self.user, 'profile'):
            self.user.profile.email_verified = True
            self.user.profile.save()
        
        # Activate user account
        self.user.is_active = True
        self.user.save()
        
        return True

    class Meta:
        verbose_name = "Email Verification"
        verbose_name_plural = "Email Verifications"
        ordering = ['-created_at']


class MilestoneAchievement(models.Model):
    MILESTONE_TYPE_CHOICES = [
        ('surveys_completed', 'Surveys Completed'),
        ('polls_completed', 'Polls Completed'),
        ('points_earned', 'Points Earned'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='milestone_achievements'
    )
    milestone_type = models.CharField(max_length=32, choices=MILESTONE_TYPE_CHOICES)
    threshold = models.PositiveIntegerField()
    achieved_value = models.PositiveIntegerField()
    prize_name = models.CharField(max_length=255)
    achieved_at = models.DateTimeField(auto_now_add=True)
    email_sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('user', 'milestone_type', 'threshold')
        ordering = ['-achieved_at']
        verbose_name = 'Milestone Achievement'
        verbose_name_plural = 'Milestone Achievements'

    def __str__(self):
        return (
            f"{self.user.username} - {self.get_milestone_type_display()} "
            f"{self.threshold}"
        )


def journal_image_upload_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/journal_images/<slug>/<filename>
    return f'journal_images/{instance.slug or "unsaved"}/{filename}'


class JournalPost(models.Model):
    """A blog-style journal article shown on the public Journal page."""
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True, help_text='A URL-friendly version of the title. Will be automatically generated from the title.')
    author = models.CharField(max_length=100, blank=True, default='Sudraw Team')
    excerpt = models.TextField(blank=True, help_text='Short summary shown on the Journal listing page.')
    content = RichTextField(help_text='Full article content (supports rich text)')
    featured_image = models.ImageField(upload_to=journal_image_upload_path, blank=True, null=True)
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at']
        verbose_name = 'Journal Post'
        verbose_name_plural = 'Journal Posts'

    @classmethod
    def make_slug(cls, title, instance=None):
        """Generate a unique slug from the title."""
        slug = slugify(title)
        original_slug = slug
        counter = 1

        while cls.objects.filter(slug=slug).exclude(pk=getattr(instance, 'pk', None)).exists():
            slug = f"{original_slug}-{counter}"
            counter += 1

        return slug

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.__class__.make_slug(self.title, self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
