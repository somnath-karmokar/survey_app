from django.contrib import admin, messages
from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin
from django.db.models.deletion import ProtectedError
from django.utils.translation import gettext_lazy as _
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django import forms
from django.db import models
from django.forms import CheckboxSelectMultiple
from ckeditor.widgets import CKEditorWidget
from .models import (
    SurveyCategory, Survey, Question, Choice, SurveyResponse, Answer,
    LuckyDrawEntry, UserProfile, Country, EmailVerification, MilestoneAchievement,
    Poll, PollQuestion, PollChoice, PollResponse, PollAnswer, CountryLuckyDrawConfig,
    WalletTransaction, UserWallet, WalletWithdrawalRequest, JournalPost, JournalCategory, PrivacyPolicy, AboutUs
)
from django.utils.safestring import mark_safe
from django.urls import path
from django.http import JsonResponse, HttpResponseRedirect
from django.db.models import Count, Max, Q

# Custom Admin Site
class SurveyAdminSite(AdminSite):
    site_header = _('Sudraw Administration')
    site_title = _('Sudraw Admin')
    index_title = _('Welcome to Sudraw Admin')
    
    def get_app_list(self, request, app_label=None):
        """
        Return a sorted list of all the installed apps that have been
        registered in this site.
        """
        app_dict = self._build_app_dict(request)
        
        # Sort the apps alphabetically.
        app_list = sorted(app_dict.values(), key=lambda x: x['name'].lower())
        
        # Sort the models alphabetically within each app.
        for app in app_list:
            app['models'].sort(key=lambda x: x['name'])
            
        return app_list


class SafeDeleteAdminMixin:
    """Adds a per-row delete link in list display and handles delete failures gracefully."""

    def get_list_display(self, request):
        list_display = super().get_list_display(request)
        if self.has_delete_permission(request) and 'delete_link' not in list_display:
            return list_display + ('delete_link',)
        return list_display

    def delete_link(self, obj):
        # Provide a direct link to the admin delete confirmation page for the object
        opts = obj._meta
        url = reverse(f'admin:{opts.app_label}_{opts.model_name}_delete', args=[obj.pk])
        return format_html('<a class="deletelink" href="{}">Delete</a>', url)
    delete_link.short_description = 'Delete'

    def _format_protected_error(self, obj_label, exc: ProtectedError) -> str:
        protected = getattr(exc, 'protected_objects', None)
        if protected:
            names = sorted({str(o) for o in protected})
            if len(names) > 5:
                sample = ", ".join(names[:5])
                sample += f" +{len(names) - 5} more"
            else:
                sample = ", ".join(names)
            return f"Cannot delete {obj_label}: it is referenced by {sample}. Delete those first."
        return f"Cannot delete {obj_label}: {exc}"

    def delete_model(self, request, obj):
        try:
            super().delete_model(request, obj)
        except ProtectedError as e:
            messages.error(request, self._format_protected_error(obj, e))

    def delete_queryset(self, request, queryset):
        try:
            super().delete_queryset(request, queryset)
        except ProtectedError as e:
            messages.error(request, self._format_protected_error('selected items', e))


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1
    fields = ('choice_text',)  # Removed 'order' since the field doesn't exist
    show_change_link = True


class PollChoiceInline(admin.TabularInline):
    model = PollChoice
    extra = 1
    fields = ('choice_text', 'order')


class PollQuestionInline(admin.TabularInline):
    model = PollQuestion
    extra = 1
    fields = ('question_text', 'question_type', 'is_required', 'order')
    show_change_link = True


class PollAnswerInline(admin.TabularInline):
    model = PollAnswer
    extra = 0
    readonly_fields = ('question', 'get_answer_display')
    fields = ('question', 'get_answer_display')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def get_answer_display(self, obj):
        if obj.question.question_type == 'text':
            return obj.text_answer
        if obj.question.question_type == 'rating':
            return obj.rating_value
        return ", ".join(choice.choice_text for choice in obj.selected_choices.all())
    get_answer_display.short_description = 'Answer'


class PollAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    inlines = [PollQuestionInline]
    list_display = ('title', 'country', 'question_count', 'response_count', 'is_active', 'order', 'created_at')
    list_filter = ('country', 'is_active', 'created_at')
    search_fields = ('title', 'description', 'country__name')
    list_select_related = ('country',)
    fields = ('title', 'description', 'country', 'is_active', 'order')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('country').prefetch_related('questions', 'responses')

    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = 'Questions'

    def response_count(self, obj):
        return obj.responses.count()
    response_count.short_description = 'Responses'


class PollQuestionAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    inlines = [PollChoiceInline]
    list_display = ('question_text', 'poll', 'question_type', 'is_required', 'order', 'created_at')
    list_filter = ('question_type', 'is_required', 'poll__country', 'poll')
    search_fields = ('question_text', 'poll__title')
    list_select_related = ('poll', 'poll__country')


class PollResponseAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    inlines = [PollAnswerInline]
    list_display = ('id', 'user', 'poll', 'country', 'submitted_at')
    list_filter = ('poll', 'poll__country', 'submitted_at')
    readonly_fields = ('user', 'poll', 'submitted_at')
    search_fields = ('user__username', 'user__email', 'poll__title')
    list_select_related = ('user', 'poll', 'poll__country')

    def country(self, obj):
        return obj.poll.country
    country.short_description = 'Country'


class CountryLuckyDrawConfigAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('country', 'poll_count_required', 'prize_display', 'currency_code', 'is_active', 'updated_at')
    list_filter = ('is_active', 'currency_code', 'country')
    search_fields = ('country__name', 'country__code', 'currency_code')
    list_select_related = ('country',)

    def prize_display(self, obj):
        return obj.get_prize_display()
    prize_display.short_description = 'Prize Amount'


class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('profile', 'transaction_type', 'amount_display', 'description', 'balance_after_display', 'created_at')
    list_filter = ('transaction_type', 'currency_code', 'created_at')
    search_fields = ('profile__user__username', 'profile__user__email', 'description')
    readonly_fields = (
        'profile', 'transaction_type', 'amount', 'currency_code',
        'currency_symbol', 'description', 'lucky_draw_entry',
        'balance_after', 'created_at'
    )
    list_select_related = ('profile', 'profile__user', 'lucky_draw_entry')
    date_hierarchy = 'created_at'

    def amount_display(self, obj):
        return obj.amount_display
    amount_display.short_description = 'Amount'

    def balance_after_display(self, obj):
        return obj.balance_after_display
    balance_after_display.short_description = 'Balance After'

    def has_add_permission(self, request):
        return False


class WalletWithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = (
        'profile', 'amount_display', 'payment_method', 'country',
        'status', 'created_at', 'reviewed_by', 'reviewed_at'
    )
    list_filter = ('status', 'payment_method', 'country', 'currency_code', 'created_at')
    search_fields = (
        'profile__user__username', 'profile__user__email', 'full_name',
        'email', 'paypal_email', 'bank_name', 'bank_account_number',
        'routing_number', 'sort_code', 'iban', 'nuban_number',
        'gift_card_brand', 'gift_card_email'
    )
    readonly_fields = (
        'profile', 'full_name', 'email', 'amount', 'currency_code',
        'currency_symbol', 'country', 'payment_method', 'paypal_email',
        'bank_account_name', 'bank_name', 'bank_account_number',
        'routing_number', 'sort_code', 'iban', 'nuban_number',
        'transit_number', 'institution_number', 'gift_card_brand',
        'gift_card_email', 'notes', 'reviewed_by', 'reviewed_at',
        'wallet_transaction', 'created_at', 'updated_at'
    )
    fieldsets = (
        ('Request', {
            'fields': (
                'profile', 'full_name', 'email', 'amount', 'currency_code',
                'currency_symbol', 'country', 'payment_method', 'status',
                'admin_note'
            )
        }),
        ('PayPal Details', {'fields': ('paypal_email',)}),
        ('Bank Details', {
            'fields': (
                'bank_account_name', 'bank_name', 'bank_account_number',
                'routing_number', 'sort_code', 'iban', 'nuban_number',
                'transit_number', 'institution_number'
            )
        }),
        ('Gift Card Details', {'fields': ('gift_card_brand', 'gift_card_email')}),
        ('Review', {'fields': ('reviewed_by', 'reviewed_at', 'wallet_transaction', 'notes')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )
    actions = ('approve_requests', 'reject_requests')
    list_select_related = ('profile', 'profile__user', 'country', 'reviewed_by', 'wallet_transaction')
    date_hierarchy = 'created_at'

    def amount_display(self, obj):
        return obj.amount_display
    amount_display.short_description = 'Amount'

    def save_model(self, request, obj, form, change):
        requested_status = obj.status
        old_status = None
        if change:
            old_status = WalletWithdrawalRequest.objects.only('status').get(pk=obj.pk).status

        if change and old_status != WalletWithdrawalRequest.STATUS_PENDING and requested_status != old_status:
            obj.status = old_status
            messages.error(request, 'Reviewed withdrawal requests cannot have their status changed.')
            super().save_model(request, obj, form, change)
            return

        if change and old_status == WalletWithdrawalRequest.STATUS_PENDING and requested_status in (
            WalletWithdrawalRequest.STATUS_APPROVED,
            WalletWithdrawalRequest.STATUS_REJECTED,
        ):
            obj.status = old_status
            super().save_model(request, obj, form, change)
            obj.refresh_from_db()
            try:
                if requested_status == WalletWithdrawalRequest.STATUS_APPROVED:
                    obj.approve(reviewed_by=request.user)
                    messages.success(request, 'Withdrawal approved and wallet balance debited.')
                else:
                    obj.reject(reviewed_by=request.user)
                    messages.success(request, 'Withdrawal request rejected.')
            except Exception as exc:
                messages.error(request, str(exc))
            return

        super().save_model(request, obj, form, change)

    def approve_requests(self, request, queryset):
        approved = 0
        for withdrawal in queryset.filter(status=WalletWithdrawalRequest.STATUS_PENDING):
            try:
                withdrawal.approve(reviewed_by=request.user)
                approved += 1
            except Exception as exc:
                messages.error(request, f'{withdrawal}: {exc}')
        if approved:
            messages.success(request, f'{approved} withdrawal request(s) approved.')
    approve_requests.short_description = 'Approve selected pending withdrawal requests'

    def reject_requests(self, request, queryset):
        rejected = 0
        for withdrawal in queryset.filter(status=WalletWithdrawalRequest.STATUS_PENDING):
            try:
                withdrawal.reject(reviewed_by=request.user)
                rejected += 1
            except Exception as exc:
                messages.error(request, f'{withdrawal}: {exc}')
        if rejected:
            messages.success(request, f'{rejected} withdrawal request(s) rejected.')
    reject_requests.short_description = 'Reject selected pending withdrawal requests'

    def has_add_permission(self, request):
        return False


class WalletTransactionInline(admin.TabularInline):
    model = WalletTransaction
    fk_name = 'profile'
    extra = 0
    can_delete = False
    show_change_link = True
    fields = (
        'created_at', 'transaction_type', 'amount_display',
        'description', 'balance_after_display', 'lucky_draw_entry'
    )
    readonly_fields = fields
    ordering = ('-created_at',)

    def amount_display(self, obj):
        return obj.amount_display
    amount_display.short_description = 'Amount'

    def balance_after_display(self, obj):
        return obj.balance_after_display
    balance_after_display.short_description = 'Balance After'

    def has_add_permission(self, request, obj=None):
        return False


class UserWalletAdmin(admin.ModelAdmin):
    inlines = [WalletTransactionInline]
    list_display = (
        'user', 'email', 'country', 'wallet_balance_display',
        'transaction_count', 'last_transaction_at'
    )
    list_filter = ('country',)
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    readonly_fields = (
        'user', 'email', 'country', 'phone_number', 'wallet_balance_display',
        'created_at', 'updated_at'
    )
    fields = (
        'user', 'email', 'country', 'phone_number', 'wallet_balance_display',
        'created_at', 'updated_at'
    )
    list_select_related = ('user', 'country')
    ordering = ('user__username',)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            transaction_total=Count('wallet_transactions'),
            last_transaction=Max('wallet_transactions__created_at'),
        )

    def email(self, obj):
        return obj.user.email
    email.short_description = 'Email'
    email.admin_order_field = 'user__email'

    def wallet_balance_display(self, obj):
        return obj.wallet_display
    wallet_balance_display.short_description = 'Wallet Balance'
    wallet_balance_display.admin_order_field = 'wallet_balance'

    def transaction_count(self, obj):
        return obj.transaction_total
    transaction_count.short_description = 'Transactions'
    transaction_count.admin_order_field = 'transaction_total'

    def last_transaction_at(self, obj):
        return obj.last_transaction
    last_transaction_at.short_description = 'Last Transaction'
    last_transaction_at.admin_order_field = 'last_transaction'

    def has_add_permission(self, request):
        return False


class MilestoneAchievementAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'milestone_type', 'threshold', 'achieved_value',
        'prize_name', 'achieved_at', 'email_sent_at'
    )
    list_filter = ('milestone_type', 'email_sent_at', 'achieved_at')
    search_fields = ('user__username', 'user__email', 'prize_name')
    readonly_fields = ('achieved_at', 'email_sent_at')

class QuestionAdminForm(forms.ModelForm):
    category = forms.ModelChoiceField(
        queryset=SurveyCategory.objects.all(),
        required=False,
        label='Category',
        help_text='Select a category to filter surveys'
    )
    country = forms.ModelChoiceField(
        queryset=Country.objects.all(),
        required=False,
        label='Country',
        help_text='Select a country to filter surveys'
    )

    class Meta:
        model = Question
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing question, get the first survey's category and country
        if self.instance and self.instance.pk and self.instance.surveys.exists():
            survey = self.instance.surveys.first()
            self.fields['category'].initial = survey.category
            if survey.category and hasattr(survey.category, 'country'):
                self.fields['country'].initial = survey.category.country

    def clean(self):
        cleaned_data = super().clean()
        # Remove category and region from cleaned_data as they're not model fields
        cleaned_data.pop('category', None)
        cleaned_data.pop('country', None)
        return cleaned_data
        
@admin.register(Question)
class QuestionAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    form = QuestionAdminForm
    list_display = ('question_text', 'question_type', 'is_required', 'order', 'survey_links', 'created_at')
    list_filter = ('question_type', 'is_required', 'surveys', 'surveys__category')
    search_fields = ('question_text',)
    list_editable = ('order', 'is_required')
    list_per_page = 20
    save_on_top = True
    filter_horizontal = ('surveys',)
    inlines = [ChoiceInline]  # Add this line to include the ChoiceInline
    
    fieldsets = (
        (None, {
            'fields': ('question_text', 'question_type', 'is_required', 'order', 'surveys')
        }),
    )
    
    def survey_links(self, obj):
        return ", ".join([
            f'<a href="{reverse("admin:surveys_survey_change", args=[s.id])}">{s.name}</a>'
            for s in obj.surveys.all()
        ]) or "-"
    survey_links.short_description = 'Surveys'
    survey_links.allow_tags = True
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Add the country and category fields to the form
        form.base_fields['country'] = forms.ModelChoiceField(
            queryset=Country.objects.all(),
            required=False,
            label='Country',
            help_text='Filter surveys by country'
        )
        form.base_fields['category'] = forms.ModelChoiceField(
            queryset=SurveyCategory.objects.all(),
            required=False,
            label='Category',
            help_text='Filter surveys by category'
        )
        return form
    
    class Media:
        js = (
            'admin/js/vendor/jquery/jquery.min.js',  # Ensure jQuery is loaded first
            'surveys/js/question-admin.js',
        )
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'get-surveys/',
                self.admin_site.admin_view(self.get_surveys),
                name='get_surveys',
            ),
        ]
        return custom_urls + urls
    def get_surveys(self, request):
        category_id = request.GET.get('category_id')
        country_id = request.GET.get('country_id')
        
        surveys = Survey.objects.all()
        if category_id:
            surveys = surveys.filter(category_id=category_id)
        if country_id:
            surveys = surveys.filter(category__country_id=country_id)
            
        return JsonResponse([
            {'id': s.id, 'name': str(s)}
            for s in surveys
        ], safe=False)
    def save_model(self, request, obj, form, change):
        # First save the question without M2M
        super().save_model(request, obj, form, change)
        
        # Then handle the M2M relationship
        if 'surveys' in form.cleaned_data:
            obj.surveys.set(form.cleaned_data['surveys'])

class QuestionInline(admin.TabularInline):
    model = Question.surveys.through
    extra = 1
    verbose_name = "Question"
    verbose_name_plural = "Questions"
    fields = ('question_display',)  # Show only the display field
    readonly_fields = ('question_display',)
    can_delete = True  # This enables the delete checkbox
    show_change_link = True
    
    def question_display(self, obj):
        if obj and hasattr(obj, 'question'):
            return obj.question.question_text
        return "No question selected"
    question_display.short_description = 'Question'
    
    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if obj and obj.category and 'question' in formset.form.base_fields:
            formset.form.base_fields['question'].queryset = Question.objects.filter(
                surveys__category=obj.category
            ).distinct()
        return formset
    
    def get_fields(self, request, obj=None):
        # Only show the display field
        return ('question_display',)
    
    def has_add_permission(self, request, obj=None):
        # Only allow adding questions when editing an existing survey
        return obj is not None and obj.pk is not None


class CountryAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code')
    list_editable = ('is_active',)
    list_per_page = 20
    ordering = ('name',)
    
    actions = ['populate_countries']
    
    def populate_countries(self, request, queryset):
        from django_countries import countries
        from django.db import transaction
        
        created_count = 0
        updated_count = 0
        
        with transaction.atomic():
            for code, name in countries:
                country, created = Country.objects.get_or_create(
                    code=code,
                    defaults={'name': name}
                )
                if not created and country.name != name:
                    country.name = name
                    country.save()
                    updated_count += 1
                elif created:
                    created_count += 1
        
        self.message_user(
            request,
            f'Successfully populated countries. Created: {created_count}, Updated: {updated_count}.'
        )
    populate_countries.short_description = 'Populate countries from django-countries'


class SurveyAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    change_form_template = 'admin/surveys/survey/change_form.html'
    inlines = [QuestionInline]
    list_display = ('name', 'category', 'level', 'get_country', 'question_count', 'is_active', 'created_at')
    list_filter = ('category', 'category__country', 'is_active', 'created_at', 'level')
    search_fields = ('name', 'description')
    list_editable = ('is_active', 'level')
    list_select_related = ('category', 'category__country')
    list_per_page = 20
    save_on_top = True
    date_hierarchy = 'created_at'
    filter_horizontal = ('questions',)
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'category', 'level', 'is_active')
        }),
    )
    
    def formfield_for_dbfield(self, db_field, **kwargs):
        if db_field.name == 'level':
            kwargs['widget'] = forms.Select(choices=[(i, f'Level {i}') for i in range(1, 11)])
        return super().formfield_for_dbfield(db_field, **kwargs)
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('questions')
    
    def get_country(self, obj):
        return obj.category.country if obj.category and hasattr(obj.category, 'country') else None
    get_country.short_description = 'Country'
    get_country.admin_order_field = 'category__country'
    
    def question_count(self, obj):
        count = obj.questions.count()
        return format_html('<a href="{}?survey__id__exact={}">{}</a>', 
                          reverse('admin:surveys_question_changelist'), 
                          obj.id, 
                          count)
    question_count.short_description = 'Questions'
    question_count.admin_order_field = 'questions_count'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:survey_id>/questions/', 
                self.admin_site.admin_view(self.view_questions),
                name='survey-questions',
            ),
        ]
        return custom_urls + urls

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        # Provide URL for the dedicated question-ordering view (if needed)
        url = reverse('admin:survey-questions', args=[object_id])
        if request.GET:
            query = request.GET.urlencode()
            if query:
                url = f"{url}?{query}"
        extra_context['question_order_url'] = url

        # Provide question list for inline ordering directly on the survey change form
        survey = self.get_object(request, object_id)
        if survey:
            extra_context['questions_for_reorder'] = survey.questions.all().order_by('order', 'id')

        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Persist question order from the survey change form
        order_data = request.POST.get('question_order', '')
        if order_data:
            try:
                order_list = [int(x) for x in order_data.split(',') if x]
                for idx, qid in enumerate(order_list, 1):
                    Question.objects.filter(pk=qid, surveys=obj).update(order=idx)
            except ValueError:
                pass
    
    def view_questions(self, request, survey_id):
        """
        Custom view to display questions for a specific survey
        """
        from django.shortcuts import get_object_or_404
        from django.contrib import messages
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        
        survey = get_object_or_404(Survey, pk=survey_id)
        
        if request.method == 'POST':
            # Handle question reordering
            order_data = request.POST.get('question_order', '')
            if order_data:
                try:
                    order_mapping = {}
                    for idx, question_id in enumerate(order_data.split(','), 1):
                        order_mapping[int(question_id)] = idx
                    
                    # Update the order for each question
                    for question in survey.questions.all():
                        if question.id in order_mapping:
                            question.order = order_mapping[question.id]
                            question.save(update_fields=['order'])
                    
                    messages.success(request, 'Question order updated successfully.')
                except Exception as e:
                    messages.error(request, f'Error updating question order: {str(e)}')
            
            return HttpResponseRedirect(request.path)
        
        # Get questions ordered by their order field
        questions = survey.questions.order_by('order')
        
        context = dict(
            self.admin_site.each_context(request),
            title=f'Questions for {survey.name}',
            survey=survey,
            questions=questions,
            opts=Survey._meta,
            has_add_permission=True,
            has_change_permission=True,
            has_delete_permission=True,
            has_view_permission=True,
        )
        
        return TemplateResponse(
            request,
            'admin/surveys/survey/view_questions.html',
            context,
        )
    
    def response_change(self, request, obj):
        """
        Handle the response after the 'Save' button is pressed.
        """
        if "_add_questions" in request.POST:
            # Redirect to the questions management page
            return HttpResponseRedirect(
                reverse("admin:survey-questions", args=[obj.id])
            )
        return super().response_change(request, obj)

class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    readonly_fields = ('question', 'get_answer_display')
    can_delete = True
    
    def get_answer_display(self, obj):
        if obj.question.question_type == 'text':
            return obj.text_answer
        elif obj.question.question_type == 'choice':
            return ", ".join([str(choice) for choice in obj.selected_choices.all()])
        elif obj.question.question_type == 'rating':
            return obj.rating_value
        return ""
    get_answer_display.short_description = 'Answer'

class SurveyResponseAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'user', 'survey', 'completed_at', 'time_spent')
    list_filter = ('survey', 'completed_at')
    inlines = [AnswerInline]
    readonly_fields = ('user', 'survey', 'completed_at', 'time_spent')
    list_select_related = ('user', 'survey')
    search_fields = ('user__username', 'survey__name')
    date_hierarchy = 'completed_at'
    
    def time_spent(self, obj):
        # Since we don't have started_at, we can't calculate time spent
        # You might want to add started_at to the model in the future
        return "Not available"
    time_spent.short_description = 'Time Spent'

class LuckyDrawEntryAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        'user', 'draw_type', 'source_title', 'created_at', 'is_winner',
        'guessed_number', 'winning_number', 'prize',
        'surveys_at_play', 'polls_at_play'
    )
    list_filter = ('draw_type', 'is_winner', 'created_at', 'survey', 'poll')
    search_fields = (
        'user__username', 'user__email', 'prize',
        'survey__name', 'poll__title'
    )
    readonly_fields = (
        'user', 'draw_type', 'survey', 'poll', 'created_at', 'is_winner',
        'guessed_number', 'winning_number', 'prize',
        'surveys_at_play', 'polls_at_play'
    )
    list_select_related = ('user', 'survey', 'poll')
    list_per_page = 20
    date_hierarchy = 'created_at'

    def source_title(self, obj):
        if obj.draw_type == LuckyDrawEntry.DRAW_TYPE_POLL:
            return obj.poll.title if obj.poll else '-'
        return obj.survey.name if obj.survey else '-'
    source_title.short_description = 'Poll / Survey'
    
    def has_add_permission(self, request):
        # Disable adding entries through admin since they should be created by the system
        return False

class EmailVerificationAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    list_display = ('user', 'email', 'is_verified', 'created_at', 'expires_at', 'verified_at', 'token_preview')
    list_filter = ('is_verified', 'created_at', 'expires_at')
    search_fields = ('user__username', 'user__email', 'email')
    readonly_fields = ('token', 'created_at', 'expires_at', 'verified_at')
    list_per_page = 20
    date_hierarchy = 'created_at'
    
    fieldsets = (
        (None, {
            'fields': ('user', 'email', 'token')
        }),
        ('Status', {
            'fields': ('is_verified', 'verified_at')
        }),
        ('Dates', {
            'fields': ('created_at', 'expires_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        # Disable adding verification tokens through admin
        return False
    
    def token_preview(self, obj):
        """Show a truncated version of the token"""
        if obj.token:
            return f"{obj.token[:16]}..." if len(obj.token) > 16 else obj.token
        return "-"
    token_preview.short_description = 'Token Preview'
    
    def is_valid_token(self, obj):
        """Display if token is still valid"""
        if obj.is_verified:
            return "Verified ✓"
        return "Valid" if obj.is_valid() else "Expired ✗"
    is_valid_token.short_description = 'Token Status'

# Create custom admin site instance
survey_admin_site = SurveyAdminSite(name='survey_admin')

# Unregister the default User and Group admins if they're already registered
if admin.site.is_registered(User):
    admin.site.unregister(User)
if admin.site.is_registered(Group):
    admin.site.unregister(Group)

# Unregister from our custom admin site if needed
if User in survey_admin_site._registry:
    survey_admin_site.unregister(User)
if Group in survey_admin_site._registry:
    survey_admin_site.unregister(Group)

class SurveyCategoryAdminForm(forms.ModelForm):
    class Meta:
        model = SurveyCategory
        fields = '__all__'
        widgets = {
            'description': CKEditorWidget(),
        }
        widgets = {
            'description': CKEditorWidget(),
        }

class SurveyCategoryAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    form = SurveyCategoryAdminForm
    list_display = ('name', 'slug', 'country', 'parent', 'order', 'image_preview', 'survey_count', 'created_at')
    list_filter = ('country', 'parent', 'created_at')
    search_fields = ('name', 'description', 'slug', 'country__name')
    list_editable = ('order',)
    list_per_page = 20
    save_on_top = True
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('image_preview', 'created_at', 'updated_at')
    fieldsets = (
            (None, {
                'fields': ('name', 'slug', 'country', 'parent', 'order', 'description')
            }),
            ('Image', {
                'fields': ('image', 'image_preview'),
                'classes': ('collapse',)
            }),
            ('Metadata', {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',)
            }),
        )  
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('surveys')
    
    def survey_count(self, obj):
        return obj.surveys.count()
    survey_count.short_description = 'Surveys'
    
    def image_preview(self, obj):
        if obj.image:
            from django.utils.html import format_html
            return format_html('<img src="{}" style="max-height: 100px;" />', obj.image.url)
        return "No image"
    image_preview.short_description = 'Preview'
    
    def save_model(self, request, obj, form, change):
        if not obj.slug:  # Only set slug if it's not already set
            obj.slug = obj._meta.model.objects.make_slug(obj.name)
        super().save_model(request, obj, form, change)
    
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Limit parent choices to exclude self and its descendants
        if obj:
            form.base_fields['parent'].queryset = SurveyCategory.objects.exclude(
                id__in=self.get_descendant_ids(obj)
            )
        return form
    
    def get_descendant_ids(self, category, id_list=None):
        if id_list is None:
            id_list = []
        id_list.append(category.id)
        for child in category.children.all():
            self.get_descendant_ids(child, id_list)
        return id_list


class JournalCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'image_preview', 'post_count', 'created_at')
    search_fields = ('name', 'slug')
    list_editable = ('order',)
    list_per_page = 20
    save_on_top = True
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('image_preview', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'order')
        }),
        ('Image', {
            'fields': ('image', 'image_preview'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('journal_posts')

    def post_count(self, obj):
        return obj.journal_posts.count()
    post_count.short_description = 'Posts'

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 100px;" />', obj.image.url)
        return "No image"
    image_preview.short_description = 'Preview'

    def save_model(self, request, obj, form, change):
        if not obj.slug:
            obj.slug = obj._meta.model.make_slug(obj.name, obj)
        super().save_model(request, obj, form, change)


class JournalPostAdminForm(forms.ModelForm):
    class Meta:
        model = JournalPost
        fields = '__all__'
        widgets = {
            'content': CKEditorWidget(),
        }


class JournalPostAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    form = JournalPostAdminForm
    list_display = ('title', 'slug', 'category', 'author', 'is_published', 'published_at', 'image_preview')
    list_filter = ('is_published', 'category', 'published_at')
    search_fields = ('title', 'excerpt', 'content', 'author')
    list_editable = ('is_published',)
    list_per_page = 20
    save_on_top = True
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('image_preview', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('title', 'slug', 'category', 'author', 'is_published', 'published_at', 'excerpt', 'content')
        }),
        ('Featured Image', {
            'fields': ('featured_image', 'image_preview'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def image_preview(self, obj):
        if obj.featured_image:
            return format_html('<img src="{}" style="max-height: 100px;" />', obj.featured_image.url)
        return "No image"
    image_preview.short_description = 'Preview'

    def save_model(self, request, obj, form, change):
        if not obj.slug:
            obj.slug = obj._meta.model.make_slug(obj.title, obj)
        super().save_model(request, obj, form, change)


class PrivacyPolicyAdminForm(forms.ModelForm):
    class Meta:
        model = PrivacyPolicy
        fields = '__all__'
        widgets = {
            'content': CKEditorWidget(),
        }


class PrivacyPolicyAdmin(admin.ModelAdmin):
    """Singleton admin — only one Privacy Policy record can exist and it cannot be deleted."""
    form = PrivacyPolicyAdminForm
    list_display = ('title', 'updated_at')
    readonly_fields = ('updated_at',)
    save_on_top = True

    def has_add_permission(self, request):
        return not PrivacyPolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        policy = PrivacyPolicy.objects.first()
        if policy:
            url = reverse(f'{self.admin_site.name}:surveys_privacypolicy_change', args=[policy.pk])
            return HttpResponseRedirect(url)
        return super().changelist_view(request, extra_context)


class AboutUsAdminForm(forms.ModelForm):
    class Meta:
        model = AboutUs
        fields = '__all__'
        widgets = {
            'content': CKEditorWidget(),
        }


class AboutUsAdmin(admin.ModelAdmin):
    """Singleton admin — only one About Us record can exist and it cannot be deleted."""
    form = AboutUsAdminForm
    list_display = ('title', 'updated_at')
    readonly_fields = ('updated_at',)
    save_on_top = True

    def has_add_permission(self, request):
        return not AboutUs.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        about = AboutUs.objects.first()
        if about:
            url = reverse(f'{self.admin_site.name}:surveys_aboutus_change', args=[about.pk])
            return HttpResponseRedirect(url)
        return super().changelist_view(request, extra_context)


# Custom User Admin
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'

class CustomUserAdmin(SafeDeleteAdminMixin, BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'country', 'wallet', 'is_active', 'date_joined')
    list_filter = ('is_active', 'groups', 'date_joined', 'profile__country')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('-date_joined',)
    filter_horizontal = ('groups', 'user_permissions',)

    def country(self, obj):
        if hasattr(obj, 'profile') and obj.profile and obj.profile.country:
            return obj.profile.country
        return None
    country.short_description = 'Country'
    country.admin_order_field = 'profile__country'

    def wallet(self, obj):
        if hasattr(obj, 'profile') and obj.profile:
            return obj.profile.wallet_display
        return '-'
    wallet.short_description = 'Wallet'

    # Only show non-staff users in the admin
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Prefetch profile + country to avoid N+1 queries
        qs = qs.select_related('profile__country')
        return qs.filter(is_staff=False, is_superuser=False)

    # Fields shown when adding users
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
    )

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'email')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        return super().get_inline_instances(request, obj)

class DefaultModelAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    """Default admin with delete link support."""
    pass

# Register models with the custom admin site
survey_admin_site.register(User, CustomUserAdmin)
survey_admin_site.register(Group, GroupAdmin)  # Using default GroupAdmin
survey_admin_site.register(Country, CountryAdmin)
survey_admin_site.register(SurveyCategory, SurveyCategoryAdmin)
survey_admin_site.register(Survey, SurveyAdmin)
survey_admin_site.register(Question, QuestionAdmin)
survey_admin_site.register(Choice, DefaultModelAdmin)
survey_admin_site.register(Poll, PollAdmin)
survey_admin_site.register(PollQuestion, PollQuestionAdmin)
survey_admin_site.register(PollChoice, DefaultModelAdmin)
survey_admin_site.register(PollResponse, PollResponseAdmin)
survey_admin_site.register(PollAnswer, DefaultModelAdmin)
survey_admin_site.register(CountryLuckyDrawConfig, CountryLuckyDrawConfigAdmin)
survey_admin_site.register(UserWallet, UserWalletAdmin)
survey_admin_site.register(WalletTransaction, WalletTransactionAdmin)
survey_admin_site.register(WalletWithdrawalRequest, WalletWithdrawalRequestAdmin)
survey_admin_site.register(SurveyResponse, SurveyResponseAdmin)
survey_admin_site.register(EmailVerification, EmailVerificationAdmin)
survey_admin_site.register(Answer, DefaultModelAdmin)
survey_admin_site.register(LuckyDrawEntry, LuckyDrawEntryAdmin)
survey_admin_site.register(MilestoneAchievement, MilestoneAchievementAdmin)
survey_admin_site.register(JournalCategory, JournalCategoryAdmin)
survey_admin_site.register(JournalPost, JournalPostAdmin)
survey_admin_site.register(PrivacyPolicy, PrivacyPolicyAdmin)
survey_admin_site.register(AboutUs, AboutUsAdmin)

# Register with the default admin site (only non-auth models)
admin.site.register(SurveyCategory, SurveyCategoryAdmin)
admin.site.register(Survey, SurveyAdmin)
admin.site.register(Choice, DefaultModelAdmin)
admin.site.register(Answer, DefaultModelAdmin)
admin.site.register(SurveyResponse, SurveyResponseAdmin)
admin.site.register(Poll, PollAdmin)
admin.site.register(PollQuestion, PollQuestionAdmin)
admin.site.register(PollChoice, DefaultModelAdmin)
admin.site.register(PollResponse, PollResponseAdmin)
admin.site.register(PollAnswer, DefaultModelAdmin)
admin.site.register(CountryLuckyDrawConfig, CountryLuckyDrawConfigAdmin)
admin.site.register(UserWallet, UserWalletAdmin)
admin.site.register(WalletTransaction, WalletTransactionAdmin)
admin.site.register(WalletWithdrawalRequest, WalletWithdrawalRequestAdmin)
admin.site.register(LuckyDrawEntry, LuckyDrawEntryAdmin)
admin.site.register(MilestoneAchievement, MilestoneAchievementAdmin)
admin.site.register(JournalCategory, JournalCategoryAdmin)
admin.site.register(JournalPost, JournalPostAdmin)
admin.site.register(PrivacyPolicy, PrivacyPolicyAdmin)
admin.site.register(AboutUs, AboutUsAdmin)
