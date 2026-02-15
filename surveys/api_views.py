from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Q
from .models import (
    SurveyCategory, Survey, Question, 
    Choice, SurveyResponse, Answer, LuckyDrawEntry
)
from .serializers import (
    SurveyCategorySerializer, SurveySerializer, 
    QuestionSerializer, SurveyResponseSerializer,
    AnswerSerializer, LuckyDrawEntrySerializer,
    UserSerializer
)
from django.contrib.auth.models import User

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAdminUser]  # Only admin can manage users

class SurveyCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SurveyCategory.objects.all()
    serializer_class = SurveyCategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

class SurveyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SurveySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Survey.objects.filter(is_active=True)
        category = self.request.query_params.get('category', None)
        if category is not None:
            queryset = queryset.filter(category_id=category)
        return queryset

class QuestionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = QuestionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Question.objects.all()
        survey_id = self.request.query_params.get('survey', None)
        if survey_id is not None:
            queryset = queryset.filter(survey_id=survey_id)
        return queryset

class SurveyResponseViewSet(viewsets.ModelViewSet):
    serializer_class = SurveyResponseSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SurveyResponse.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['get'])
    def completed_surveys(self, request):
        current_month = timezone.now().month
        current_year = timezone.now().year
        
        completed = SurveyResponse.objects.filter(
            user=request.user,
            completed_at__month=current_month,
            completed_at__year=current_year
        ).values_list('survey_id', flat=True)
        
        return Response({
            'completed_surveys': list(completed),
            'month': current_month,
            'year': current_year
        })

class LuckyDrawEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LuckyDrawEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return LuckyDrawEntry.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        current_month = timezone.now().month
        current_year = timezone.now().year
        
        # Check if user already has an entry for this month
        if LuckyDrawEntry.objects.filter(
            user=self.request.user,
            month=current_month,
            year=current_year
        ).exists():
            raise serializers.ValidationError("You have already entered the lucky draw this month.")
        
        # Check if user has completed all surveys
        active_surveys = Survey.objects.filter(is_active=True)
        completed_surveys = SurveyResponse.objects.filter(
            user=self.request.user,
            completed_at__month=current_month,
            completed_at__year=current_year
        ).values_list('survey_id', flat=True)
        
        missing_surveys = active_surveys.exclude(id__in=completed_surveys).exists()
        if missing_surveys:
            raise serializers.ValidationError("You must complete all active surveys to enter the lucky draw.")
        
        # Check if number is available
        selected_number = self.request.data.get('selected_number')
        if not (1 <= int(selected_number) <= 100):
            raise serializers.ValidationError("Please select a number between 1 and 100.")
            
        if LuckyDrawEntry.objects.filter(
            month=current_month,
            year=current_year,
            selected_number=selected_number
        ).exists():
            raise serializers.ValidationError("This number is already taken. Please choose another one.")
        
        serializer.save(
            user=self.request.user,
            month=current_month,
            year=current_year
        )

    @action(detail=False, methods=['get'])
    def check_number(self, request):
        number = request.query_params.get('number')
        if not number or not number.isdigit():
            return Response(
                {'error': 'Invalid number'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        number = int(number)
        if not (1 <= number <= 100):
            return Response(
                {'error': 'Number must be between 1 and 100'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        current_month = timezone.now().month
        current_year = timezone.now().year
        
        is_taken = LuckyDrawEntry.objects.filter(
            month=current_month,
            year=current_year,
            selected_number=number
        ).exists()
        
        return Response({
            'available': not is_taken,
            'number': number
        })
