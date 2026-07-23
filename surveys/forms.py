from django import forms
from django.forms import ModelForm, formset_factory, BaseFormSet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import (
    Country, Choice, SurveyResponse, Answer, LuckyDrawEntry, UserProfile,
    Question, PollResponse, PollAnswer, WalletWithdrawalRequest
)
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth import get_user_model
from django.core.files.images import get_image_dimensions
User = get_user_model()


class WalletWithdrawalRequestForm(forms.ModelForm):
    class Meta:
        model = WalletWithdrawalRequest
        fields = (
            'full_name', 'email', 'amount', 'country', 'payment_method',
            'paypal_email', 'bank_account_name', 'bank_name', 'bank_account_number',
            'routing_number', 'sort_code', 'iban', 'nuban_number',
            'transit_number', 'institution_number', 'gift_card_brand',
            'gift_card_email', 'notes'
        )
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Name on bank/payment account'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Your email address'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}),
            'country': forms.Select(attrs={'class': 'form-select', 'data-withdraw-country': 'true'}),
            'payment_method': forms.Select(attrs={'class': 'form-select', 'data-payment-method': 'true'}),
            'paypal_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'PayPal email address'}),
            'bank_account_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account holder name'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bank name'}),
            'bank_account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account number'}),
            'routing_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '9 digit routing number'}),
            'sort_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '6 digit sort code'}),
            'iban': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'IBAN'}),
            'nuban_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '10 digit NUBAN'}),
            'transit_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '5 digit transit number'}),
            'institution_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '3 digit institution number'}),
            'gift_card_brand': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Amazon, Flipkart, etc.'}),
            'gift_card_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email for gift card delivery'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional notes for admin'}),
        }

    def __init__(self, *args, **kwargs):
        self.profile = kwargs.pop('profile')
        self.is_first_withdrawal = kwargs.pop('is_first_withdrawal', False)
        super().__init__(*args, **kwargs)
        self.fields['country'].queryset = Country.objects.filter(is_active=True).order_by('name')
        self.fields['country'].empty_label = 'Select country of residence'
        self.fields['full_name'].initial = self.profile.user.get_full_name() or self.profile.user.username
        self.fields['email'].initial = self.profile.user.email
        if self.profile.country_id:
            self.fields['country'].initial = self.profile.country_id

        if self.is_first_withdrawal:
            self.fields['payment_method'].choices = [
                (WalletWithdrawalRequest.PAYMENT_METHOD_BANK, 'Direct Bank Transfer'),
            ]
            self.fields['payment_method'].initial = WalletWithdrawalRequest.PAYMENT_METHOD_BANK

        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        wallet_balance = self.profile.wallet_balance or 0
        if amount and amount > wallet_balance:
            raise forms.ValidationError('Withdrawal amount cannot be greater than your current wallet balance.')
        return amount

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method')

        if self.is_first_withdrawal and payment_method != WalletWithdrawalRequest.PAYMENT_METHOD_BANK:
            self.add_error('payment_method', 'Your first withdrawal must be via bank transfer.')

        country = cleaned_data.get('country')
        country_code = str(getattr(country, 'code', '') or '').upper()

        if payment_method == WalletWithdrawalRequest.PAYMENT_METHOD_PAYPAL:
            if not cleaned_data.get('paypal_email'):
                self.add_error('paypal_email', 'PayPal email address is required.')

        if payment_method == WalletWithdrawalRequest.PAYMENT_METHOD_BANK:
            if not cleaned_data.get('bank_account_name'):
                self.add_error('bank_account_name', 'Account holder name is required.')
            if not cleaned_data.get('bank_account_number') and country_code not in ('GB', 'NG'):
                self.add_error('bank_account_number', 'Account number is required.')

            if country_code == 'US' and not cleaned_data.get('routing_number'):
                self.add_error('routing_number', 'ABA routing number is required for United States bank transfer.')
            elif country_code == 'GB' and not (cleaned_data.get('sort_code') and cleaned_data.get('bank_account_number')) and not cleaned_data.get('iban'):
                self.add_error('iban', 'Provide either Sort Code with Account Number, or IBAN for United Kingdom transfer.')
            elif country_code == 'NG':
                if not cleaned_data.get('nuban_number'):
                    self.add_error('nuban_number', 'NUBAN account number is required for Nigeria bank transfer.')
                if not cleaned_data.get('bank_name'):
                    self.add_error('bank_name', 'Bank name is required for Nigeria bank transfer.')
            elif country_code == 'CA':
                if not cleaned_data.get('transit_number'):
                    self.add_error('transit_number', 'Transit number is required for Canada EFT transfer.')
                if not cleaned_data.get('institution_number'):
                    self.add_error('institution_number', 'Institution number is required for Canada EFT transfer.')

        if payment_method == WalletWithdrawalRequest.PAYMENT_METHOD_GIFT_CARD:
            if not cleaned_data.get('gift_card_brand'):
                self.add_error('gift_card_brand', 'Gift card brand is required.')
            if not cleaned_data.get('gift_card_email'):
                self.add_error('gift_card_email', 'Gift card delivery email is required.')

        return cleaned_data

    def save(self, commit=True):
        request = super().save(commit=False)
        request.profile = self.profile
        request.currency_code = self.profile.wallet_currency_code
        request.currency_symbol = self.profile.wallet_currency_symbol
        if commit:
            request.save()
        return request

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
    # Location fields
    # City and country are now mandatory for registration per requirement.
    city = forms.CharField(max_length=100, required=True)
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
        max_value=timezone.now().year - 18,  # Minimum age 18
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
            max_year = current_year - 18  # Minimum age 18

            if year_of_birth > max_year:
                raise forms.ValidationError(
                    f'You must be at least 18 years old to register. Maximum year allowed is {max_year}.'
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
        self.fields['first_name'] = forms.CharField(initial=user.first_name, max_length=30, required=False, disabled=True)
        self.fields['last_name'] = forms.CharField(initial=user.last_name, max_length=150, required=False, disabled=True)
        self.fields['email'] = forms.EmailField(initial=user.email, required=True, disabled=True)
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
        if commit:
            profile.save()
        return profile

class SurveyResponseForm(forms.Form):
    OTHER_CHOICE_VALUE = '__other__'

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
            choices = [(str(c.id), c.choice_text) for c in question.choices.all()]
            choices.append((self.OTHER_CHOICE_VALUE, 'Other'))
            self.fields[field_name] = forms.ChoiceField(
                label=question.question_text,
                required=question.is_required,
                choices=choices,
                widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
                help_text=help_text
            )
            self.add_other_text_field(question, field_name)
        elif question.question_type == 'multiple_choice':
            choices = [(str(c.id), c.choice_text) for c in question.choices.all()]
            choices.append((self.OTHER_CHOICE_VALUE, 'Other'))
            self.fields[field_name] = forms.MultipleChoiceField(
                label=question.question_text,
                required=question.is_required,
                choices=choices,
                widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
                help_text=help_text
            )
            self.add_other_text_field(question, field_name)
        elif question.question_type == 'rating':
            self.fields[field_name] = forms.IntegerField(
                label=question.question_text,
                required=question.is_required,
                min_value=1,
                max_value=5,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'type': 'range', 'min': '1', 'max': '5'}),
                help_text=help_text
            )

        if field_name in self.fields:
            self.fields[field_name].question = question

    def add_other_text_field(self, question, choice_field_name):
        other_field_name = f'{choice_field_name}_other'
        self.fields[other_field_name] = forms.CharField(
            label='Other',
            required=False,
            widget=forms.TextInput(attrs={
                'class': 'form-control other-answer-input',
                'placeholder': 'Please specify',
                'data_other_for': choice_field_name,
                'data-other-for': choice_field_name,
                'data_question_type': 'other_text',
            })
        )
        self.fields[other_field_name].question = question

    def clean(self):
        cleaned_data = super().clean()

        for field_name, field in self.fields.items():
            question = getattr(field, 'question', None)
            if not question or question.question_type not in ['single_choice', 'multiple_choice']:
                continue
            if field_name.endswith('_other'):
                continue

            answer_value = cleaned_data.get(field_name)
            other_text = (cleaned_data.get(f'{field_name}_other') or '').strip()
            other_selected = False

            if question.question_type == 'multiple_choice':
                other_selected = self.OTHER_CHOICE_VALUE in (answer_value or [])
            else:
                other_selected = answer_value == self.OTHER_CHOICE_VALUE

            if other_selected and not other_text:
                self.add_error(f'{field_name}_other', 'Please give value for Other.')

        return cleaned_data

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
        other_text = (self.cleaned_data.get(f'{field_name}_other') or '').strip()
        
        if answer_value or other_text:  # Only save if there's an answer
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
                    selected_choice_ids = [value for value in answer_value if value != self.OTHER_CHOICE_VALUE]
                    answer.selected_choices.set(selected_choice_ids)
                else:
                    selected_choice_ids = [] if answer_value == self.OTHER_CHOICE_VALUE else [answer_value]
                    answer.selected_choices.set(selected_choice_ids)
                if other_text:
                    answer.text_answer = other_text
                    answer.save(update_fields=['text_answer'])
            elif question.question_type == 'text':
                # For text answers
                answer.text_answer = str(answer_value)
                answer.save()
            elif question.question_type == 'rating':
                # For rating questions
                answer.rating_value = int(answer_value)
                answer.save()
        
        return survey_response


class PollResponseForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.poll = kwargs.pop('poll', None)
        self.question_id = kwargs.pop('question_id', None)
        super().__init__(*args, **kwargs)

        if self.poll and self.question_id:
            try:
                question = self.poll.questions.get(id=self.question_id)
                self.add_question_field(question)
            except self.poll.questions.model.DoesNotExist:
                pass
        elif self.poll:
            for question in self.poll.questions.all().order_by('order', 'id'):
                self.add_question_field(question)

    def add_question_field(self, question):
        field_name = f'poll_question_{question.id}'

        if question.question_type == 'text':
            self.fields[field_name] = forms.CharField(
                label=question.question_text,
                required=question.is_required,
                widget=forms.Textarea(attrs={
                    'class': 'form-control',
                    'rows': 3,
                    'placeholder': 'Type your answer here...',
                    'data_question_type': question.question_type
                })
            )
        elif question.question_type == 'multiple_choice':
            self.fields[field_name] = forms.ModelMultipleChoiceField(
                label=question.question_text,
                required=question.is_required,
                queryset=question.choices.all(),
                widget=forms.CheckboxSelectMultiple(attrs={
                    'class': 'form-check-input',
                    'data_question_type': question.question_type
                })
            )
        elif question.question_type == 'single_choice':
            self.fields[field_name] = forms.ModelChoiceField(
                label=question.question_text,
                required=question.is_required,
                queryset=question.choices.all(),
                widget=forms.RadioSelect(attrs={
                    'class': 'form-check-input',
                    'data_question_type': question.question_type
                })
            )
        elif question.question_type == 'rating':
            self.fields[field_name] = forms.IntegerField(
                label=question.question_text,
                required=question.is_required,
                min_value=1,
                max_value=5,
                initial=3,
                widget=forms.NumberInput(attrs={
                    'class': 'form-range',
                    'type': 'range',
                    'min': '1',
                    'max': '5',
                    'data_question_type': question.question_type
                })
            )

        self.fields[field_name].question = question

    def save(self, user, poll):
        if not self.is_valid():
            raise ValueError("Cannot save invalid poll form")

        response = PollResponse.objects.create(user=user, poll=poll)

        for question in poll.questions.all().order_by('order', 'id'):
            field_name = f'poll_question_{question.id}'
            answer_value = self.cleaned_data.get(field_name)

            if not answer_value and not question.is_required:
                continue

            answer = PollAnswer.objects.create(
                response=response,
                question=question,
                text_answer=str(answer_value) if question.question_type == 'text' else None,
                rating_value=int(answer_value) if question.question_type == 'rating' and answer_value else None
            )

            if question.question_type == 'multiple_choice' and answer_value:
                answer.selected_choices.set(answer_value)
            elif question.question_type == 'single_choice' and answer_value:
                answer.selected_choices.set([answer_value])

        return response
