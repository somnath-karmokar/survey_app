import os
import sys
import django
import re
from docx import Document
from django.db import transaction

# -------------------------------------------------
# 1️⃣ Django setup
# -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "survey_app.settings")
django.setup()

# -------------------------------------------------
# 2️⃣ Import models AFTER setup
# -------------------------------------------------
from surveys.models import (
    Country,
    SurveyCategory,
    Survey,
    Question,
    Choice
)

# -------------------------------------------------
# 3️⃣ Constants
# -------------------------------------------------
DOC_PATH = os.path.join(BASE_DIR, "data", "U.K.2 -  Furniture & Home.docx")
CATEGORY_NAME = "Furniture & Home"

QUESTION_STARTERS = (
    "On a scale of",
    "What ",
    "How ",
    "Which ",
    "Do you ",
    "Is there ",
    "In one word",
)

SECTION_REGEX = re.compile(r"Section\s+\d+:")


# -------------------------------------------------
# 4️⃣ Helpers
# -------------------------------------------------
def is_question_line(text: str) -> bool:
    if text.endswith("?"):
        return True
    return text.startswith(QUESTION_STARTERS)


def detect_question_type(text: str) -> str:
    if "On a scale of 1-10" in text:
        return "rating"
    if "Select up to" in text or "Select primary" in text:
        return "multiple_choice"
    return "single_choice"


def clean_option(text: str) -> str:
    return text.lstrip("*").strip()


def save_choices(question, options):
    if not question or question.question_type not in ("single_choice", "multiple_choice"):
        return

    for opt in options:
        Choice.objects.get_or_create(
            question=question,
            choice_text=clean_option(opt)
        )


# -------------------------------------------------
# 5️⃣ Main importer
# -------------------------------------------------
@transaction.atomic
def import_survey(country_code: str):
    print("\n🚀 STARTING SURVEY IMPORT")

    country = Country.objects.get(code=country_code)
    print(f"🌍 Country: {country}")

    category, _ = SurveyCategory.objects.get_or_create(
        name=CATEGORY_NAME,
        defaults={"country": country, "order": 1}
    )
    print(f"📂 Category: {category.name}")

    doc = Document(DOC_PATH)

    current_survey = None
    current_question = None
    option_buffer = []
    inside_section = False
    question_counter = {}

    for para in doc.paragraphs:
        # 🔑 CRITICAL FIX: split paragraph into logical lines
        lines = [line.strip() for line in para.text.split("\n") if line.strip()]

        for text in lines:

            # -------------------------
            # Section header
            # -------------------------
            if SECTION_REGEX.match(text):
                save_choices(current_question, option_buffer)

                current_survey, _ = Survey.objects.get_or_create(
                    name=text,
                    category=category,
                    defaults={"is_active": True}
                )

                inside_section = True
                current_question = None
                option_buffer = []
                question_counter[text] = 0

                print(f"\n📝 {text}")
                continue

            if not inside_section:
                continue

            # -------------------------
            # Option (bullet or normal)
            # -------------------------
            if text.startswith("*"):
                option_buffer.append(text)
                continue

            # -------------------------
            # Open text marker
            # -------------------------
            if "Open Text Field" in text:
                if current_question:
                    current_question.question_type = "text"
                    current_question.save(update_fields=["question_type"])
                continue

            # -------------------------
            # Question
            # -------------------------
            if is_question_line(text):
                save_choices(current_question, option_buffer)

                q_type = detect_question_type(text)

                current_question, created = Question.objects.get_or_create(
                    question_text=text,
                    defaults={
                        "question_type": q_type,
                        "is_required": True
                    }
                )

                if not created and current_question.question_type != q_type:
                    current_question.question_type = q_type
                    current_question.save(update_fields=["question_type"])

                current_question.surveys.add(current_survey)
                option_buffer = []

                question_counter[current_survey.name] += 1
                print(f"   ❓ Q{question_counter[current_survey.name]}: {text}")
                continue

            # -------------------------
            # Plain option line
            # -------------------------
            option_buffer.append(text)

    save_choices(current_question, option_buffer)

    print("\n✅ IMPORT COMPLETED")
    for section, count in question_counter.items():
        print(f"📊 {section} → {count} questions")


# -------------------------------------------------
# 6️⃣ Entry point
# -------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("❌ Usage: python script.py <COUNTRY_CODE>")
        sys.exit(1)

    import_survey(sys.argv[1].upper())
