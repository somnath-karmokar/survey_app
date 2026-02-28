from rest_framework import serializers
from django.contrib.auth.models import User
from django.conf import settings
from .models import (
    SurveyCategory, Survey, Question, 
    Choice, SurveyResponse, Answer, LuckyDrawEntry
)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name')
        read_only_fields = ('id',)

class ChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choice
        fields = ('id', 'choice_text')
        read_only_fields = ('id',)

class QuestionSerializer(serializers.ModelSerializer):
    choices = ChoiceSerializer(many=True, read_only=True)
    
    class Meta:
        model = Question
        fields = ('id', 'question_text', 'question_type', 'is_required', 'order', 'choices')
        read_only_fields = ('id',)

class SurveyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyCategory
        fields = ('id', 'name', 'description')
        read_only_fields = ('id',)

class SurveySerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    category = SurveyCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=SurveyCategory.objects.all(),
        source='category',
        write_only=True
    )
    
    class Meta:
        model = Survey
        fields = ('id', 'name', 'description', 'is_active', 'category', 'category_id', 'level', 'questions', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')

class AnswerSerializer(serializers.ModelSerializer):
    question_id = serializers.PrimaryKeyRelatedField(
        queryset=Question.objects.all(),
        source='question',
        write_only=True
    )
    selected_choices = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Choice.objects.all(),
        required=False
    )
    
    class Meta:
        model = Answer
        fields = ('id', 'question_id', 'text_answer', 'selected_choices', 'rating_value')
        read_only_fields = ('id',)
    
    def validate(self, data):
        question = data.get('question')
        text_answer = data.get('text_answer')
        selected_choices = data.get('selected_choices', [])
        rating_value = data.get('rating_value')
        
        if question.is_required:
            if question.question_type == 'text' and not text_answer:
                raise serializers.ValidationError("This field is required.")
            elif question.question_type in ['single_choice', 'multiple_choice'] and not selected_choices:
                raise serializers.ValidationError("Please select at least one option.")
            elif question.question_type == 'rating' and not rating_value:
                raise serializers.ValidationError("Please provide a rating.")
        
        if question.question_type == 'single_choice' and len(selected_choices) > 1:
            raise serializers.ValidationError("Only one choice is allowed for this question.")
            
        if question.question_type == 'rating' and rating_value is not None:
            if not (1 <= rating_value <= 5):
                raise serializers.ValidationError("Rating must be between 1 and 5.")
        
        return data

class SurveyResponseSerializer(serializers.ModelSerializer):
    answers = AnswerSerializer(many=True, required=True)
    survey_id = serializers.PrimaryKeyRelatedField(
        queryset=Survey.objects.filter(is_active=True),
        source='survey',
        write_only=True
    )
    
    class Meta:
        model = SurveyResponse
        fields = ('id', 'survey_id', 'completed_at', 'answers')
        read_only_fields = ('id', 'completed_at')
    
    def create(self, validated_data):
        answers_data = validated_data.pop('answers')
        survey_response = SurveyResponse.objects.create(
            user=self.context['request'].user,
            **validated_data
        )
        
        for answer_data in answers_data:
            selected_choices = answer_data.pop('selected_choices', [])
            answer = Answer.objects.create(
                response=survey_response,
                **answer_data
            )
            answer.selected_choices.set(selected_choices)
        
        return survey_response

class LuckyDrawEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LuckyDrawEntry
        # guessed_number is provided by client; other fields are generated
        fields = (
            'id',
            'guessed_number',
            'winning_number',
            'prize',
            'surveys_at_play',
            'created_at',
            'is_winner',
        )
        read_only_fields = (
            'id',
            'winning_number',
            'prize',
            'surveys_at_play',
            'created_at',
            'is_winner',
        )
    
    def validate_guessed_number(self, value):
        start = getattr(settings, 'LUCKY_DRAW_CONFIG', {}).get('NUMBER_RANGE_START', 1)
        end = getattr(settings, 'LUCKY_DRAW_CONFIG', {}).get('NUMBER_RANGE_END', 100)
        if not (start <= value <= end):
            raise serializers.ValidationError(f"Guessed number must be between {start} and {end}.")
        return value
