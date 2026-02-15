"""
URL configuration for survey_app project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from surveys.admin import survey_admin_site
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from surveys import api_views

# Password Reset URLs
password_reset_patterns = [
    path('password_reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt'
    ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),
]

# Create a router for our API
router = DefaultRouter()
router.register(r'api/users', api_views.UserViewSet)
router.register(r'api/categories', api_views.SurveyCategoryViewSet)
router.register(r'api/surveys', api_views.SurveyViewSet, basename='survey')
router.register(r'api/questions', api_views.QuestionViewSet, basename='question')
router.register(r'api/responses', api_views.SurveyResponseViewSet, basename='surveyresponse')
router.register(r'api/lucky-draw', api_views.LuckyDrawEntryViewSet, basename='luckydrawentry')

urlpatterns = [
    # Grappelli URLS
    path('grappelli/', include('grappelli.urls')),
    
    # Custom admin site
    path('admin/', survey_admin_site.urls),
    
    # Survey app URLs (for web interface) - Moved to the top to take precedence
    path('', include('surveys.urls')),  # This will be the main entry point
    
    # API Authentication
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # API URLs - moved under /api/ prefix
    path('api/', include(router.urls)),
    
    # API Documentation
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    
    # Password Reset URLs
    path('', include(password_reset_patterns)),
]

# Serve static and media files in development
if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    
    # Serve media files
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    
    # Serve static files
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # This will serve static files from STATICFILES_DIRS in development
    urlpatterns += staticfiles_urlpatterns()
