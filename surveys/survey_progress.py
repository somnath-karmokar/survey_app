"""In-progress surveys: parts, saved answers and resume.

Each category holds one long survey (a screening question, then ~120 questions)
shown as SURVEY_CONFIG['SURVEY_PARTS'] (8) equal parts. Answers are saved to
the database question by question on an open SurveyResponse (completed_at is
null), so a user always continues where they left off, on any device. A user
with an open survey must finish it before starting a survey in another category.
"""
from django.conf import settings
from django.db.models import Exists, OuterRef

from .models import Answer, Choice, SurveyResponse


def survey_part_count():
    return max(1, int(getattr(settings, 'SURVEY_CONFIG', {}).get('SURVEY_PARTS', 8)))


def screening_question_ids(questions):
    """Ids of screening questions: the ones with an untruthful (disqualifying) option."""
    ids = [q.id for q in questions]
    return set(Choice.objects.filter(question_id__in=ids, is_disqualifying=True)
               .values_list('question_id', flat=True))


def question_parts(questions, screening_ids):
    """Part number (1..PARTS) for each question in order; 0 for screening questions.

    The non-screening questions are split into equal consecutive parts
    (120 questions -> 8 parts of 15).
    """
    parts_total = survey_part_count()
    main = [q for q in questions if q.id not in screening_ids]
    count = len(main) or 1
    part_of = {q.id: (i * parts_total // count) + 1 for i, q in enumerate(main)}
    return [part_of.get(q.id, 0) for q in questions]


def open_response(user, survey=None):
    """The user's unfinished response (for one survey, or any active survey), or None."""
    queryset = SurveyResponse.objects.filter(user=user, completed_at__isnull=True, survey__is_active=True)
    if survey is not None:
        queryset = queryset.filter(survey=survey)
    return queryset.select_related('survey__category').order_by('-started_at').first()


def answered_question_ids(response):
    if response is None:
        return set()
    return set(response.answers.values_list('question_id', flat=True))


def open_survey_summary(user):
    """For banners: {'survey', 'answered', 'total', 'part', 'parts'} of the open survey, or None."""
    response = open_response(user)
    if response is None:
        return None
    questions = list(response.survey.questions.order_by('order', 'id'))
    if not questions:
        return None
    answered = answered_question_ids(response)
    parts = question_parts(questions, screening_question_ids(questions))
    next_index = next((i for i, q in enumerate(questions) if q.id not in answered), len(questions) - 1)
    return {
        'response': response,
        'survey': response.survey,
        'answered': len(answered),
        'total': len(questions),
        'part': max(1, parts[next_index]),
        'parts': survey_part_count(),
    }


def survey_questions_answered(user):
    """Survey questions this user has answered in total (screening questions excluded).

    Counts finished and unfinished surveys alike; one answer per question per
    survey attempt, so going back and changing an answer doesn't count twice.
    """
    screening = Choice.objects.filter(question=OuterRef('question'), is_disqualifying=True)
    return (Answer.objects.filter(response__user=user)
            .annotate(is_screening=Exists(screening))
            .filter(is_screening=False)
            .count())


# ── Sample cap: each category collects at most N completed responses per country ──

def category_sample_cap(category):
    """Most completed responses this category may collect, or None for unlimited.

    From the country's draw config (category_sample_cap; empty = unlimited, as for
    Nigeria). Countries without a config use SURVEY_CONFIG['CATEGORY_SAMPLE_CAP'] (10),
    except those in CATEGORY_SAMPLE_CAP_EXEMPT (Nigeria).
    """
    from .models import CountryLuckyDrawConfig
    country = category.country
    if country is None:
        return None
    config = CountryLuckyDrawConfig.objects.filter(country=country).first()
    if config is not None:
        return config.category_sample_cap
    survey_config = getattr(settings, 'SURVEY_CONFIG', {})
    if str(country.code).upper() in survey_config.get('CATEGORY_SAMPLE_CAP_EXEMPT', ('NG',)):
        return None
    return survey_config.get('CATEGORY_SAMPLE_CAP', 10)


def category_sample_status(survey, user=None):
    """{'cap', 'completed', 'in_progress', 'full'} for a survey's category.

    A place is taken by every completed response and every unfinished one (so
    people who have started can always finish). `full` is True when no place is
    left for `user`; someone already answering this survey is never blocked.
    """
    cap = category_sample_cap(survey.category)
    responses = SurveyResponse.objects.filter(survey__category=survey.category)
    completed = responses.filter(completed_at__isnull=False).count()
    unfinished = responses.filter(completed_at__isnull=True)
    if user is not None:
        unfinished = unfinished.exclude(user=user)
    in_progress = unfinished.count()
    own_open = user is not None and responses.filter(user=user, completed_at__isnull=True).exists()
    full = cap is not None and not own_open and completed + in_progress >= cap
    return {'cap': cap, 'completed': completed, 'in_progress': in_progress, 'full': full}


# ── Attempts: how a response was answered, sitting by sitting (Appendix 3) ────────

def attempt_gap_minutes():
    return int(getattr(settings, 'SURVEY_CONFIG', {}).get('ATTEMPT_GAP_MINUTES', 30))


def response_attempts(response, questions=None):
    """The sittings in which this response was answered.

    Consecutive answers belong to the same attempt unless more than
    ATTEMPT_GAP_MINUTES (30) passed between them. Returns
    [{'number', 'first', 'last', 'count', 'started_at', 'ended_at', 'seconds'}],
    where first/last are question labels ("Q1".."Q120", "Screening").
    """
    from datetime import timedelta
    questions = questions if questions is not None else list(response.survey.questions.order_by('order', 'id'))
    parts = question_parts(questions, screening_question_ids(questions))
    labels, number = {}, 0
    for question, part in zip(questions, parts):
        if part:
            number += 1
        labels[question.id] = f'Q{number}' if part else 'Screening'
    answers = list(response.answers.filter(answered_at__isnull=False).order_by('answered_at', 'id'))
    gap = timedelta(minutes=attempt_gap_minutes())
    attempts = []
    for answer in answers:
        if not attempts or answer.answered_at - attempts[-1]['ended_at'] > gap:
            attempts.append({'number': len(attempts) + 1, 'first': labels.get(answer.question_id, '?'),
                             'started_at': answer.answered_at, 'count': 0, 'seconds': 0})
        current = attempts[-1]
        current['last'] = labels.get(answer.question_id, '?')
        current['ended_at'] = answer.answered_at
        current['count'] += 1
        current['seconds'] += answer.time_spent_seconds or 0
    return attempts


def full_survey_ids(user, surveys):
    """Ids of the given surveys this user can't start because their category is full.

    Same rule as category_sample_status, counted for many surveys at once.
    """
    from django.db.models import Count, Q
    surveys = list(surveys)
    if not surveys:
        return set()
    caps = {}
    for survey in surveys:
        key = survey.category.country_id
        if key not in caps:
            caps[key] = category_sample_cap(survey.category)
    category_ids = [s.category_id for s in surveys if caps.get(s.category.country_id) is not None]
    if not category_ids:
        return set()
    taken = dict(
        SurveyResponse.objects.filter(survey__category_id__in=category_ids)
        .exclude(user=user, completed_at__isnull=True)
        .values('survey__category_id').annotate(n=Count('id')).values_list('survey__category_id', 'n')
    )
    own_open = set(SurveyResponse.objects.filter(user=user, completed_at__isnull=True)
                   .values_list('survey_id', flat=True)) if user.is_authenticated else set()
    full = set()
    for survey in surveys:
        cap = caps.get(survey.category.country_id)
        if cap is not None and survey.id not in own_open and taken.get(survey.category_id, 0) >= cap:
            full.add(survey.id)
    return full
