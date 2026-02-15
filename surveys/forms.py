from django import forms
from django.forms import ModelForm, formset_factory, BaseFormSet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Country, Choice, SurveyResponse, Answer, LuckyDrawEntry, UserProfile, Question
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth import get_user_model
from django.core.files.images import get_image_dimensions
User = get_user_model()

class BaseAnswerFormSet(BaseFormSet):
    def clean(self):
        """Check that at least one answer is provided for required questions."""
        if any(self.errors):
            return

        for form in self.forms:
            if form.cleaned_data.get('DELETE'):
                continue
            
            question = form.cleaned_data.get('question')
            text_answer = form.cleaned_data.get('text_answer')
            selected_choices = form.cleaned_data.get('selected_choices')
            rating_value = form.cleaned_data.get('rating_value')
            
            if question.is_required:
                if question.question_type == 'text' and not text_answer:
                    raise forms.ValidationError(
                        _('This is a required question. Please provide an answer.')
                    )
                elif question.question_type in ['single_choice', 'multiple_choice'] and not selected_choices:
                    raise forms.ValidationError(
                        _('Please select at least one option for this question.')
                    )
                elif question.question_type == 'rating' and not rating_value:
                    raise forms.ValidationError(
                        _('Please provide a rating for this question.')
                    )


class AnswerForm(forms.ModelForm):
    class Meta:
        model = Answer
        fields = ['question', 'text_answer', 'selected_choices', 'rating_value']
        widgets = {
            'question': forms.HiddenInput(),
            'text_answer': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Type your answer here...'
            }),
            'selected_choices': forms.CheckboxSelectMultiple(attrs={
                'class': 'form-check-input'
            }),
            'rating_value': forms.RadioSelect(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['selected_choices'].queryset = self.initial.get('question').choices.all()
        
        # Customize the form based on question type
        question = self.initial.get('question')
        if question:
            if question.question_type == 'text':
                self.fields['text_answer'].required = question.is_required
                self.fields['selected_choices'].widget = forms.HiddenInput()
                self.fields['rating_value'].widget = forms.HiddenInput()
            elif question.question_type == 'single_choice':
                self.fields['selected_choices'].widget = forms.RadioSelect(attrs={'class': 'form-check-input'})
                self.fields['text_answer'].widget = forms.HiddenInput()
                self.fields['rating_value'].widget = forms.HiddenInput()
                self.fields['selected_choices'].required = question.is_required
            elif question.question_type == 'multiple_choice':
                self.fields['selected_choices'].widget = forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
                self.fields['text_answer'].widget = forms.HiddenInput()
                self.fields['rating_value'].widget = forms.HiddenInput()
                self.fields['selected_choices'].required = question.is_required
            elif question.question_type == 'rating':
                self.fields['rating_value'].widget = forms.NumberInput(attrs={
                    'class': 'form-control',
                    'min': 1,
                    'max': 5,
                    'style': 'width: 80px; display: inline-block;'
                })
                self.fields['text_answer'].widget = forms.HiddenInput()
                self.fields['selected_choices'].widget = forms.HiddenInput()
                self.fields['rating_value'].required = question.is_required


class SurveyResponseForm(forms.ModelForm):
    class Meta:
        model = SurveyResponse
        fields = []  # We'll add fields dynamically

    def __init__(self, survey, *args, **kwargs):
        self.survey = survey
        super().__init__(*args, **kwargs)
        
        # In the __init__ method of SurveyResponseForm, add the data-question-type attribute
        for question in survey.questions.all().order_by('order'):
            field_name = f'question_{question.id}'
            if question.question_type == 'text':
                self.fields[field_name] = forms.CharField(
                    widget=forms.Textarea(attrs={
                        'class': 'form-control',
                        'rows': 3,
                        'data_question_type': question.question_type
                    }),
                    required=question.is_required,
                    label=question.question_text
                )
            elif question.question_type == 'single_choice':
                self.fields[field_name] = forms.ModelChoiceField(
                    queryset=question.choices.all(),
                    widget=forms.RadioSelect(attrs={
                        'class': 'form-check-input',
                        'data_question_type': question.question_type
                    }),
                    required=question.is_required,
                    label=question.question_text
                )
            elif question.question_type == 'multiple_choice':
                self.fields[field_name] = forms.ModelMultipleChoiceField(
                    queryset=question.choices.all(),
                    widget=forms.CheckboxSelectMultiple(attrs={
                        'class': 'form-check-input',
                        'data_question_type': question.question_type
                    }),
                    required=question.is_required,
                    label=question.question_text
                )
            elif question.question_type == 'rating':
                self.fields[field_name] = forms.IntegerField(
                    widget=forms.NumberInput(attrs={
                        'class': 'form-range',
                        'type': 'range',
                        'min': 1,
                        'max': 5,
                        'data_question_type': question.question_type
                    }),
                    required=question.is_required,
                    label=question.question_text
                )
            
            # Store the question object in the field for template access
            self.fields[field_name].question = question


class UserRegistrationForm(UserCreationForm):
    """Custom user registration form that includes user type and name fields."""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter your email'})
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'})
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'})
    )
    user_type = forms.ChoiceField(
        choices=UserProfile.USER_TYPE_CHOICES,
        initial='frontend',
        widget=forms.HiddenInput(),  # Hidden since we're setting it to 'frontend' for web users
        required=False
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password1', 'password2', 'user_type')
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Choose a username'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set up password fields with Bootstrap classes
        self.fields['password1'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Create a password'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Confirm password'})
        # Set user_type to 'frontend' by default for web signups
        self.initial['user_type'] = 'frontend'
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
            # Create user profile with the selected user type
            UserProfile.objects.create(
                user=user,
                user_type=self.cleaned_data.get('user_type', 'frontend')
            )
        return user

    def clean(self):
        cleaned_data = super().clean()
        
        # Add any custom validation here if needed
        
        return cleaned_data

class UserRegisterForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=30, required=True)
    middle_name = forms.CharField(max_length=100, required=False)
    last_name = forms.CharField(max_length=30, required=True)
    city = forms.CharField(max_length=100, required=False)
    state = forms.CharField(max_length=100, required=False)
    country = forms.ModelChoiceField(
        queryset=Country.objects.none(),  # Will be set in __init__
        required=True,
        label="Country",
        empty_label="Select Country"
    )
    year_of_birth = forms.IntegerField(
        required=False,
        min_value=1900,
        max_value=timezone.now().year - 16,  # Minimum age 16
        widget=forms.NumberInput(attrs={'placeholder': 'Year of birth (e.g., 1990)'})
    )
    profile_picture = forms.ImageField(required=False)
    
    class Meta:
        model = User
        fields = ['email', 'first_name', 'middle_name', 'last_name',
                 'city', 'state', 'country', 'year_of_birth', 'profile_picture']
    def __init__(self, *args, **kwargs):
        country_queryset = kwargs.pop('country_queryset', None)
        super().__init__(*args, **kwargs)
        
        if country_queryset is not None:
            self.fields['country'].queryset = country_queryset
        else:
            self.fields['country'].queryset = Country.objects.all()
        
        # Set email as username field
        self.fields['email'].label = "Email/Username"
        self.fields['email'].help_text = "This will be used as your username for login"

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # Check if email already exists in User model
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        # Check if username (email) already exists
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return email

    def clean_year_of_birth(self):
        year_of_birth = self.cleaned_data.get('year_of_birth')
        if year_of_birth:
            current_year = timezone.now().year
            max_year = current_year - 16  # Minimum age 16
            
            if year_of_birth > max_year:
                raise forms.ValidationError(
                    f'You must be at least 16 years old to register. Maximum year allowed is {max_year}.'
                )
            
            if year_of_birth < 1900:
                raise forms.ValidationError('Year of birth cannot be before 1900.')
        
        return year_of_birth

    def save(self, commit=True):
        print(f'Form cleaned data: {self.cleaned_data}')
        # Create user with email as username and no password
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']  # Use email as username
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        # Set a random password that won't be used (Django requires it)
        user.set_password(User.objects.make_random_password())
        
        if commit:
            user.save()
            # Create or update user profile
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.middle_name = self.cleaned_data.get('middle_name', '')
            profile.city = self.cleaned_data.get('city', '')
            profile.state = self.cleaned_data.get('state', '')
            profile.country = self.cleaned_data.get('country')
            
            # Convert year_of_birth to date_of_birth if provided
            year_of_birth = self.cleaned_data.get('year_of_birth')
            if year_of_birth:
                from datetime import date
                profile.date_of_birth = date(year_of_birth, 1, 1)  # Default to January 1st
                
            if self.cleaned_data.get('profile_picture'):
                profile.profile_picture = self.cleaned_data['profile_picture']
            profile.user_type = 'frontend'
            profile.save()
        return user
        
class EditProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ('phone_number', 'bio', 'profile_picture', 'address', 'date_of_birth')
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3}),
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 2}),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add user fields to the form
        user = self.instance.user
        self.fields['first_name'] = forms.CharField(initial=user.first_name, max_length=30, required=False)
        self.fields['last_name'] = forms.CharField(initial=user.last_name, max_length=150, required=False)
        self.fields['email'] = forms.EmailField(initial=user.email, required=True)
    def clean_profile_picture(self):
        picture = self.cleaned_data.get('profile_picture')
        if picture:
            try:
                # Validate image size (max 2MB)
                if picture.size > 2 * 1024 * 1024:
                    raise forms.ValidationError("Image file too large (max 2MB)")
                
                # Validate image dimensions
                w, h = get_image_dimensions(picture)
                if w > 1000 or h > 1000:
                    raise forms.ValidationError("Image dimensions too large (max 1000x1000px)")
                    
            except AttributeError:
                # Handles case when we get an image that was not uploaded
                pass
                
        return picture
    def save(self, commit=True):
        profile = super().save(commit=False)
        # Update user fields
        user = profile.user
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        
        if commit:
            user.save()
            profile.save()
        return profile

class SurveyResponseForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.survey = kwargs.pop('survey', None)
        self.question_id = kwargs.pop('question_id', None)
        super().__init__(*args, **kwargs)
        
        if self.survey and self.question_id:
            try:
                question = self.survey.questions.get(id=self.question_id)
                self.add_question_field(question)
            except Question.DoesNotExist:
                pass

    def add_question_field(self, question):
        field_name = f'question_{question.id}'
        help_text = getattr(question, 'help_text', '') or ''
        
        if question.question_type == 'text':
            self.fields[field_name] = forms.CharField(
                label=question.question_text,
                required=question.is_required,
                widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
                help_text=help_text
            )
        elif question.question_type == 'single_choice':
            choices = [(c.id, c.choice_text) for c in question.choices.all()]
            self.fields[field_name] = forms.ChoiceField(
                label=question.question_text,
                required=question.is_required,
                choices=choices,
                widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
                help_text=help_text
            )
        elif question.question_type == 'multiple_choice':
            choices = [(c.id, c.choice_text) for c in question.choices.all()]
            self.fields[field_name] = forms.MultipleChoiceField(
                label=question.question_text,
                required=question.is_required,
                choices=choices,
                widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
                help_text=help_text
            )
        elif question.question_type == 'rating':
            self.fields[field_name] = forms.IntegerField(
                label=question.question_text,
                required=question.is_required,
                min_value=1,
                max_value=5,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'type': 'range', 'min': '1', 'max': '5'}),
                help_text=help_text
            )

    def save(self, user, survey, commit=True):
        """Save the survey response and answers"""
        if not self.is_valid():
            raise ValueError("Cannot save invalid form")
            
        # Get or create the survey response
        survey_response, created = SurveyResponse.objects.get_or_create(
            user=user,
            survey=survey,
            defaults={'completed_at': timezone.now()}
        )
        
        # Get the current question
        question = Question.objects.get(id=self.question_id)
        
        # Save the answer
        field_name = f'question_{question.id}'
        answer_value = self.cleaned_data.get(field_name)
        
        if answer_value:  # Only save if there's an answer
            # Delete any existing answer for this question
            Answer.objects.filter(
                response=survey_response,
                question=question
            ).delete()
            
            # Create new answer
            answer = Answer(
                response=survey_response,
                question=question
            )
            
            # Save the answer first to get an ID
            answer.save()
            
            # Now handle the answer value based on question type
            if question.question_type in ['multiple_choice', 'single_choice']:
                # For choice-based questions, set the selected choices
                if isinstance(answer_value, (list, tuple)):
                    answer.selected_choices.set(answer_value)
                else:
                    answer.selected_choices.set([answer_value])
            elif question.question_type == 'text':
                # For text answers
                answer.text_answer = str(answer_value)
                answer.save()
            elif question.question_type == 'rating':
                # For rating questions
                answer.rating_value = int(answer_value)
                answer.save()
        
        return survey_response