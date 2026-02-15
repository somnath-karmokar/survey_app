from django.urls import path
from django.contrib.auth import views as auth_views
from . import views_surveys as surveys_views
from . import views
from .views import user_profile, edit_profile
from .views_frontend import (
    HomePageView, 
    FeaturesPageView, 
    ContactPageView, 
    FAQPageView,
    SignUpView,
    CustomLoginView,
    DashboardView,
    send_otp
)
from .views_frontend import MySurveysView
from .views_categories import CategoryListView, CategoryDetailView
from django.conf import settings
from django.conf.urls.static import static
from .lucky_draw import LuckyDrawView
app_name = 'surveys'

urlpatterns = [
    # Frontend Pages
    path('', HomePageView.as_view(), name='home'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('features/', FeaturesPageView.as_view(), name='features'),
    path('contact/', ContactPageView.as_view(), name='contact'),
    path('faq/', FAQPageView.as_view(), name='faq'),
    
    # Category and Survey URLs
    path('categories/', CategoryListView.as_view(), name='category_list'),
    path('category/<slug:category_slug>/', CategoryDetailView.as_view(), name='category_detail'),
    path('surveys/', surveys_views.survey_list, name='survey_list'),
    path('surveys/<int:survey_id>/', surveys_views.survey_detail, {'question_index': 0}, name='survey_detail'),
    path('surveys/<int:survey_id>/q/<int:question_index>/', surveys_views.survey_detail, name='survey_question'),
    path('surveys/<int:survey_id>/complete/', surveys_views.survey_complete, name='survey_complete'),
    path('surveys/take/<int:survey_id>/', surveys_views.take_survey, name='take_survey'),
    path('surveys/take/<int:survey_id>/q/<int:question_id>/', surveys_views.take_survey, name='take_survey_with_question'),
    # path('take/<int:survey_id>/', views.survey_detail, name='survey_start'),


    # Lucky Draw URLs
    path('lucky-draw/', LuckyDrawView.as_view(), name='lucky_draw'),
    path('lucky-draw/number/', LuckyDrawView.as_view(), name='lucky_draw_number'),

    # Authentication URLs
    path('login/', CustomLoginView.as_view(), name='login'),
    path('signup/', SignUpView.as_view(), name='signup'),
    path('send-otp/', send_otp, name='send_otp'),
    path('logout/', auth_views.LogoutView.as_view(next_page='surveys:home'), name='logout'),
    path('profile/', user_profile, name='user_profile'),
    path('profile/edit/', edit_profile, name='edit_profile'),
    
    # Advertisement tracking
    path('survey/ad-shown/', views.survey_ad_shown, name='survey_ad_shown'),
    path('debug/ad/', views.debug_ad, name='debug_ad'),
    path('question-admin-js/', views.question_admin_js, name='question_admin_js'),
    path('my-surveys/', MySurveysView.as_view(), name='my_surveys'),
]
