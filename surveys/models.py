from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator
from ckeditor.fields import RichTextField
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField

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
    name = models.CharField(max_length=100, unique=True)
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
    
    def can_user_take_survey(self, user):
        """Check if the user can take this specific survey based on cooldown."""
        if not user.is_authenticated:
            return False, "You must be logged in to take this survey."
        
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
        """Check if this specific survey is locked for the user based on cooldown."""
        if not user.is_authenticated:
            return False, "You must be logged in to take this survey."
            
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

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'


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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lucky_draw_entries')
    created_at = models.DateTimeField(auto_now_add=True)
    is_winner = models.BooleanField(default=False)
    guessed_number = models.PositiveIntegerField()
    winning_number = models.PositiveIntegerField()
    prize = models.CharField(max_length=100, blank=True, null=True)
    surveys_at_play = models.PositiveIntegerField(help_text="Total surveys completed when this entry was created")

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Lucky Draw Entries'


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

