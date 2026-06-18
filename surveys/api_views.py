import random

from django.conf import settings
from rest_framework import viewsets, status, permissions, serializers
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
        from .lucky_draw import LuckyDrawView

        lucky_draw = LuckyDrawView()
        draw_type = serializer.validated_data.get('draw_type') or LuckyDrawEntry.DRAW_TYPE_SURVEY
        if draw_type not in {LuckyDrawEntry.DRAW_TYPE_SURVEY, LuckyDrawEntry.DRAW_TYPE_POLL}:
            raise serializers.ValidationError("Invalid lucky draw type.")
        if not lucky_draw.is_eligible(self.request.user, draw_type):
            raise serializers.ValidationError("You are not eligible for this lucky draw yet.")

        total_surveys, total_polls = lucky_draw.get_completion_counts(self.request.user)
        last_entry = lucky_draw.get_last_entry(self.request.user, draw_type)
        survey = lucky_draw.get_qualifying_survey(self.request.user, last_entry) if draw_type == LuckyDrawEntry.DRAW_TYPE_SURVEY else None
        poll = lucky_draw.get_qualifying_poll(self.request.user, last_entry) if draw_type == LuckyDrawEntry.DRAW_TYPE_POLL else None
        guessed_number = serializer.validated_data['guessed_number']
        winning_number = random.randint(
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START'],
            settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        )
        is_winner = guessed_number == winning_number
        entry = serializer.save(
            user=self.request.user,
            draw_type=draw_type,
            survey=survey,
            poll=poll,
            winning_number=winning_number,
            is_winner=is_winner,
            prize=lucky_draw.get_prize_for_user(self.request.user) if is_winner else None,
            surveys_at_play=total_surveys,
            polls_at_play=total_polls,
        )
        if is_winner:
            lucky_draw.credit_winner_wallet(entry)

    @action(detail=False, methods=['get'])
    def check_number(self, request):
        number = request.query_params.get('number')
        if not number or not number.isdigit():
            return Response(
                {'error': 'Invalid number'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        number = int(number)
        start = settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_START']
        end = settings.LUCKY_DRAW_CONFIG['NUMBER_RANGE_END']
        if not (start <= number <= end):
            return Response(
                {'error': f'Number must be between {start} and {end}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({
            'available': True,
            'number': number
        })
