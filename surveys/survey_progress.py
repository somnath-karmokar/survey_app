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
    """Part number (1, 2, ...) for each question in order; 0 for screening questions.

    Each section of the survey document (e.g. "Customer Satisfaction Index (CSI)",
    "Brand Reputation Ranking") is one part. Surveys without section titles are
    split into SURVEY_PARTS (8) equal parts.
    """
    main = [q for q in questions if q.id not in screening_ids]
    if main and all(getattr(q, 'section_title', None) for q in main):
        part_of, number, previous = {}, 0, object()
        for q in main:
            if q.section_title != previous:
                number, previous = number + 1, q.section_title
            part_of[q.id] = number
    else:
        parts_total = survey_part_count()
        count = len(main) or 1
        part_of = {q.id: (i * parts_total // count) + 1 for i, q in enumerate(main)}
    return [part_of.get(q.id, 0) for q in questions]


def part_titles(questions, parts):
    """{part number: section title} for the parts that have one."""
    titles = {}
    for q, part in zip(questions, parts):
        if part and getattr(q, 'section_title', None):
            titles.setdefault(part, q.section_title)
    return titles


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
        'parts': max(parts) or survey_part_count(),
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


# ── Sample cap: each category collects at most N responses per country per month ──
#
# The cap is set per country in the admin (Country settings -> Category sample cap;
# empty = unlimited, as for Nigeria). It counts completed surveys per calendar month
# on the country's clock (Country settings -> Time zone): when that many users have
# completed a category this month, it is locked for new users until the 1st.

def _country_config(country):
    from .models import CountryLuckyDrawConfig
    if country is None:
        return None
    return CountryLuckyDrawConfig.objects.filter(country=country).first()


def category_sample_cap(category, config=False):
    """Most responses this category may collect per month, or None for unlimited.

    From the country's settings (category_sample_cap; empty = unlimited, as for
    Nigeria). Countries without settings use SURVEY_CONFIG['CATEGORY_SAMPLE_CAP'] (10),
    except those in CATEGORY_SAMPLE_CAP_EXEMPT (Nigeria).
    """
    country = category.country
    if country is None:
        return None
    if config is False:
        config = _country_config(country)
    if config is not None:
        return config.category_sample_cap
    survey_config = getattr(settings, 'SURVEY_CONFIG', {})
    if str(country.code).upper() in survey_config.get('CATEGORY_SAMPLE_CAP_EXEMPT', ('NG',)):
        return None
    return survey_config.get('CATEGORY_SAMPLE_CAP', 10)


def sample_period(country, at=None, config=False):
    """(start of this month, start of next month) on the country's clock."""
    from django.utils import timezone
    if config is False:
        config = _country_config(country)
    tz = config.tzinfo if config is not None else timezone.get_current_timezone()
    now = timezone.localtime(at or timezone.now(), tz)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


def _completed_in(category_filter, start, end):
    """Responses completed in [start, end): the samples a category has collected that month."""
    return SurveyResponse.objects.filter(category_filter, completed_at__gte=start, completed_at__lt=end)


def category_sample_status(survey, user=None, at=None):
    """{'cap', 'completed', 'in_progress', 'full', 'reopens_on'} for a survey's category this month.

    Only completed surveys count: the category is full once `cap` users have
    completed it this month. Someone already answering it can always finish;
    `in_progress` (unfinished responses) is for information only.
    `reopens_on` is the 1st of next month.
    """
    from django.db.models import Q
    config = _country_config(survey.category.country)
    cap = category_sample_cap(survey.category, config)
    start, end = sample_period(survey.category.country, at, config)
    completed = _completed_in(Q(survey__category=survey.category), start, end).count()
    in_progress = SurveyResponse.objects.filter(survey__category=survey.category, completed_at__isnull=True).count()
    own_open = user is not None and SurveyResponse.objects.filter(
        survey__category=survey.category, user=user, completed_at__isnull=True).exists()
    full = cap is not None and not own_open and completed >= cap
    return {'cap': cap, 'completed': completed, 'in_progress': in_progress, 'full': full, 'reopens_on': end}


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


def full_survey_ids(user, surveys, at=None):
    """Ids of the given surveys this user can't start because their category is full this month.

    Same rule as category_sample_status, counted for many surveys at once.
    """
    from django.db.models import Count, Q
    surveys = list(surveys)
    if not surveys:
        return set()
    caps, periods = {}, {}
    for survey in surveys:
        key = survey.category.country_id
        if key not in caps:
            config = _country_config(survey.category.country)
            caps[key] = category_sample_cap(survey.category, config)
            periods[key] = sample_period(survey.category.country, at, config)
    taken = {}
    for country_id, cap in caps.items():
        category_ids = [s.category_id for s in surveys if s.category.country_id == country_id]
        if cap is None or not category_ids:
            continue
        start, end = periods[country_id]
        responses = _completed_in(Q(survey__category_id__in=category_ids), start, end)
        taken.update(responses.values('survey__category_id').annotate(n=Count('id'))
                     .values_list('survey__category_id', 'n'))
    own_open = set(SurveyResponse.objects.filter(user=user, completed_at__isnull=True)
                   .values_list('survey__category_id', flat=True)) if user.is_authenticated else set()
    full = set()
    for survey in surveys:
        cap = caps.get(survey.category.country_id)
        if cap is not None and survey.category_id not in own_open and taken.get(survey.category_id, 0) >= cap:
            full.add(survey.id)
    return full
