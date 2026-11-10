"""Read the 'New Enterprise Surveys' Word documents into plain survey data.

Each document is one industry for one country:

    Screening Gate (Mandatory)
    S01. Which of the following ... have you visited ...?     <- screening question (multi-select)
    McDonald's / Foodie (red) / ... / None of the above (red)
    Part 1: ...                                               <- part / section headers (skipped)
    1. Customer Satisfaction Index (CSI)
    Q01. Short title                                          <- question title
    The question itself ...                                   <- question text
    option / option / option                                  <- answer options (single choice)
    ...

Options written in red (bright or dark red) are untruthful answers (made-up
brands, "None of the above"): picking one ends the survey and suspends the user.
The green bracketed line in the screening question, e.g. "[Insert Your Target
Local Fast Food Chain]", is a type-your-own box: users whose answer is not listed
type it in. It becomes the screening question's `not_listed_label` ("fast food
chain"), and is not an option itself. Many documents carry another industry's line
(Airlines says "Gym / CrossFit Box"), so the label comes from the category name
(NOT_LISTED_LABELS) and the document's own wording is only the fallback.
"""
import os
import re

import docx

def is_red_colour(rgb):
    """Bright red (FF0000) and the dark reds some documents use (C00000, 980000)."""
    try:
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    except (TypeError, ValueError):
        return False
    return r >= 0x80 and g <= 0x40 and b <= 0x40
TERMINATE_NOTE = re.compile(r'\s*\(\s*if selected,?\s*terminate (the )?survey\s*\)\s*', re.IGNORECASE)
SCREENING_RE = re.compile(r'^S\d+\.\s*(.+)$')
QUESTION_RE = re.compile(r'^(?:Q|Question\s+)(\d+)\.\s*(.+)$', re.IGNORECASE)
SURVEY_TITLE_RE = re.compile(r'\(Questions\s+\d+\s*[–-]\s*\d+\)', re.IGNORECASE)
PLAIN_QUESTION_RE = re.compile(r'^(\d+)\.\s+(.+)$')
INDEX_HEADER_RE = re.compile(r'\bINDEX\s+\d+\b')
PART_RE = re.compile(r'^Part\s+\d+\s*[:.\-]', re.IGNORECASE)
SECTION_RE = re.compile(r'^\d+\.\s+\S')
SKIP_LINES = re.compile(r'^screening gate', re.IGNORECASE)


def is_red(paragraph):
    """True when the visible text of the paragraph is (mostly) red."""
    red = other = 0
    for run in paragraph.runs:
        text = run.text.strip()
        if not text:
            continue
        colour = run.font.color.rgb if run.font.color is not None and run.font.color.type is not None else None
        if colour is not None and is_red_colour(str(colour).upper()):
            red += len(text)
        else:
            other += len(text)
    return red > 0 and red >= other


def is_placeholder(text):
    return text.startswith('[') and text.endswith(']')


PLACEHOLDER_PREFIX = re.compile(r'^\s*insert\s+your\s+(target\s+)?(local\s+)?', re.IGNORECASE)

# Category name keyword -> what the screening question's type-your-own box asks for.
# Checked in order; the first keyword found in the (lower-case) category name wins.
NOT_LISTED_LABELS = [
    ('restaurant', 'restaurant'),                 # before 'fast food': "... (not fast food chains)"
    ('buy-now-pay-later', 'Buy Now Pay Later provider'),
    ('fast food', 'fast food chain'),
    ('airline', 'airline'),
    ('banking', 'bank'),
    ('beauty', 'beauty or cosmetics retailer'),
    ('broadband', 'broadband or cable provider'),
    ('cinema', 'cinema chain'),
    ('clothing', 'clothing retailer'),
    ('coffee', 'coffee shop or caf\u00e9'),
    ('cruise', 'cruise line or river cruise operator'),
    ('diy', 'DIY or home improvement store'),
    ('dating', 'dating app or site'),
    ('courier', 'courier or delivery service'),
    ('dental', 'dental practice'),
    ('discount', 'discount store'),
    ('energy', 'energy supplier'),
    ('food delivery', 'food delivery or takeaway app'),
    ('furniture', 'furniture or home store'),
    ('gym', 'gym or fitness club'),
    ('resort', 'holiday resort or leisure park'),
    ('white goods', 'home appliance retailer'),
    ('hotel', 'hotel or accommodation chain'),
    ('insurance', 'insurance provider'),
    ('luxury', 'luxury fashion retailer'),
    ('markets comparison', 'price comparison site'),
    ('marketplace', 'online marketplace'),
    ('optician', 'optician'),
    ('pet', 'pet shop or vet'),
    ('pharmac', 'pharmacy'),
    ('hospital', 'private hospital'),
    ('ride-hailing', 'ride-hailing or taxi service'),
    ('social media', 'social media platform'),
    ('sport brand', 'sports brand'),
    ('music', 'music streaming service'),
    ('sports services', 'sports streaming service'),
    ('supermarket', 'supermarket or grocery chain'),
    ('technology', 'electronics retailer'),
    ('telecom', 'mobile network or SIM provider'),
    ('travel', 'travel or holiday booking site'),
    ('video game', 'gaming or eSports platform'),
    ('video streaming', 'video streaming service'),
    ('credit bureau', 'credit bureau'),
]


def not_listed_label(category_name, placeholder=''):
    """What the type-your-own box asks for: from the category name, else the document's line."""
    name = (category_name or '').lower()
    for keyword, label in NOT_LISTED_LABELS:
        if keyword in name:
            return label
    inner = PLACEHOLDER_PREFIX.sub('', (placeholder or '').strip().strip('[]')).strip()
    return ' '.join(w if w.isupper() and len(w) > 1 else w.lower() for w in inner.split())


def category_name_from_filename(filename):
    name = os.path.splitext(os.path.basename(filename))[0]
    name = re.sub(r'[_\s]*-\s*ready[_\s]*$', '', name, flags=re.IGNORECASE)
    name = name.replace('_', ' ').strip(' -_')
    return re.sub(r'\s{2,}', ' ', name)


def parse_document(path):
    """{'name', 'screening': {...} | None, 'questions': [...], 'warnings': [...]}.

    Each question/screening is {'title', 'text', 'options': [{'text', 'red'}]}.
    """
    document = docx.Document(path)
    result = {'name': category_name_from_filename(path), 'screening': None, 'questions': [], 'warnings': []}
    current = None            # the question being filled
    expecting_text = False    # a Qnn title was just read; the next line is the question text

    paragraphs = [p for p in document.paragraphs if p.text.strip()]
    # Two layouts exist: "Q01. Title" questions under "1. <Section>" headers, or (e.g.
    # Opticians) "1. Title" questions under "<emoji> INDEX 1 — <Section>" headers.
    numbered_questions = not any(QUESTION_RE.match(p.text.strip()) for p in paragraphs)
    question_re = PLAIN_QUESTION_RE if numbered_questions else QUESTION_RE
    question_positions = [i for i, p in enumerate(paragraphs) if question_re.match(p.text.strip())]
    last_question_at = question_positions[-1] if question_positions else -1

    for position, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        if SKIP_LINES.match(text):
            continue
        if INDEX_HEADER_RE.search(text) or SURVEY_TITLE_RE.search(text):
            current, expecting_text = None, False
            continue

        screening = SCREENING_RE.match(text)
        question = question_re.match(text)
        style = (paragraph.style.name or '').lower() if paragraph.style is not None else ''
        if style.startswith('heading') and position > last_question_at and not expecting_text:
            # A heading after the last question (e.g. "Important scoring
            # recommendations"): designer notes, not part of the survey.
            break
        if screening and result['screening'] is None and not result['questions']:
            current = {'title': '', 'text': screening.group(1).strip(), 'options': []}
            result['screening'] = current
            expecting_text = False
            continue
        if question:
            current = {'title': question.group(2).strip(), 'text': '', 'options': [], 'number': int(question.group(1))}
            result['questions'].append(current)
            expecting_text = True
            continue
        if PART_RE.match(text) or (
            not numbered_questions and SECTION_RE.match(text) and not expecting_text and current is not result['screening']
        ):
            if current is not None and not expecting_text and not current['options']:
                result['warnings'].append(f'header after a question with no options: {text[:60]}')
            current = None if not expecting_text else current
            continue
        if current is None:
            continue
        if expecting_text:
            current['text'] = text
            expecting_text = False
            continue
        if is_placeholder(text):
            if current is result['screening'] and not current.get('placeholder'):
                current['placeholder'] = text
            continue
        red = is_red(paragraph)
        option = TERMINATE_NOTE.sub(' ', text).strip()
        if option:
            current['options'].append({'text': option, 'red': red})

    for q in result['questions']:
        q['type'] = 'single_choice'
        only = q['options'][0]['text'].lower() if len(q['options']) == 1 else ''
        if only.startswith('provide') or 'open text' in only or 'text response' in only or 'text entry' in only:
            q['type'], q['options'] = instruction_to_question(q['options'][0]['text'], q, result['warnings'])
    if result['screening'] is not None:
        result['screening']['type'] = 'multiple_choice'

    if not result['questions']:
        result['warnings'].append('no questions found')
    if result['screening'] is None:
        result['warnings'].append('no screening question')
    elif not any(o['red'] for o in result['screening']['options']):
        result['warnings'].append('screening question has no red (untruthful) option')
    if result['screening'] is not None:
        placeholder = result['screening'].pop('placeholder', '')
        result['screening']['not_listed_label'] = not_listed_label(result['name'], placeholder) if placeholder else ''
    for q in result['questions']:
        if not q['text']:
            result['warnings'].append(f"Q{q['number']:02d} has no question text")
        if q['type'] != 'text' and len(q['options']) < 2:
            result['warnings'].append(f"Q{q['number']:02d} has {len(q['options'])} option(s)")
    # Printed question numbers have slips in some documents (a skipped or repeated
    # "Qnn"); questions are imported in document order, so that's only informational.
    return result


SCALE_RE = re.compile(
    r'from\s+(\d+)\s*(?:\(([^)]*)\))?\s*to\s+(\d+)\s*(?:\(([^)]*)\))?', re.IGNORECASE,
)


def instruction_to_question(instruction, question, warnings):
    """Turn a designer note ("Provide ... radio buttons from 0 (...) to 10 (...)" or
    "Provide an open text entry box ...") into (type, options)."""
    scale = SCALE_RE.search(instruction)
    if scale and 'radio' in instruction.lower():
        low, low_label, high, high_label = int(scale.group(1)), scale.group(2), int(scale.group(3)), scale.group(4)
        options = []
        for n in range(low, high + 1):
            label = str(n)
            if n == low and low_label:
                label = f'{n} ({low_label.strip()})'
            elif n == high and high_label:
                label = f'{n} ({high_label.strip()})'
            options.append({'text': label, 'red': False})
        return 'single_choice', options
    if 'text' in instruction.lower():
        return 'text', []
    warnings.append(f"Q{question['number']:02d}: unrecognised instruction kept as an option: {instruction[:60]}")
    return 'single_choice', question['options']


def survey_files(root):
    """[(country folder, path)] for every survey document, skipping Word's ~$ lock files."""
    files = []
    for folder in sorted(os.listdir(root)):
        folder_path = os.path.join(root, folder)
        if not os.path.isdir(folder_path):
            continue
        for name in sorted(os.listdir(folder_path)):
            if name.lower().endswith('.docx') and not name.startswith('~$'):
                files.append((folder, os.path.join(folder_path, name)))
    return files
