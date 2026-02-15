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


# -------------------------------------------------
# 4️⃣ Helper
# -------------------------------------------------
def save_choices(question, options):
    if not question or question.question_type not in ("single_choice", "multiple_choice"):
        return

    for opt in options:
        Choice.objects.get_or_create(
            question=question,
            choice_text=opt.strip()
        )


# -------------------------------------------------
# 5️⃣ Main importer
# -------------------------------------------------
@transaction.atomic
def import_survey(country_code: str):
    print(f"🚀 Starting survey import for country code: {country_code}")

    # ---- Country (must exist)
    try:
        country = Country.objects.get(code=country_code)
    except Country.DoesNotExist:
        raise RuntimeError(f"❌ Country '{country_code}' does not exist")

    print(f"🌍 Using country: {country}")

    # ---- Category (FIXED LOGIC)
    try:
        category = SurveyCategory.objects.get(name=CATEGORY_NAME)
    except SurveyCategory.DoesNotExist:
        category = SurveyCategory.objects.create(
            name=CATEGORY_NAME,
            country=country,
            order=1
        )
        print(f"📂 Created category: {CATEGORY_NAME}")
    else:
        if category.country_id != country.id:
            raise RuntimeError(
                f"❌ Category '{CATEGORY_NAME}' already exists "
                f"for country {category.country}"
            )
        print(f"📂 Using existing category: {CATEGORY_NAME}")

    # ---- Load DOCX
    doc = Document(DOC_PATH)

    current_survey = None
    current_question = None
    option_buffer = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # ---- Survey section
        if re.match(r"Section\s+\d+:\s+.+", text):
            save_choices(current_question, option_buffer)

            current_survey, _ = Survey.objects.get_or_create(
                name=text,
                category=category,
                defaults={"is_active": True}
            )

            print(f"📝 Survey: {text}")
            current_question = None
            option_buffer = []
            continue

        # ---- Question
        if text.endswith("?"):
            save_choices(current_question, option_buffer)

            q_type = "single_choice"
            if "Select up to" in text or "Select primary" in text:
                q_type = "multiple_choice"

            current_question, _ = Question.objects.get_or_create(
                question_text=text,
                defaults={
                    "question_type": q_type,
                    "is_required": True,
                }
            )
            current_question.surveys.add(current_survey)
            option_buffer = []
            continue

        # ---- Rating
        if re.match(r"^\d+\s*\(", text):
            if current_question:
                current_question.question_type = "rating"
                current_question.save(update_fields=["question_type"])
            continue

        # ---- Open text
        if "Open Text Field" in text:
            if current_question:
                current_question.question_type = "text"
                current_question.save(update_fields=["question_type"])
            continue

        # ---- Option
        option_buffer.append(text)

    save_choices(current_question, option_buffer)
    print("✅ Survey import completed successfully")


# -------------------------------------------------
# 6️⃣ Entry point
# -------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("❌ Usage: python import_country_survey.py <COUNTRY_CODE>")
        sys.exit(1)

    import_survey(sys.argv[1].upper())
