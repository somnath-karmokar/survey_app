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
# 3️⃣ Regex & constants
# -------------------------------------------------
SECTION_REGEX = re.compile(r"(?:\d+\.\s*)?Section\s+\d+\s*:", re.IGNORECASE)
CATEGORY_CLEAN_REGEX = re.compile(r"^[A-Za-z\.]+\d+\s*-\s*")

QUESTION_STARTERS = (
    "On a scale of",
    "What ",
    "How ",
    "Which ",
    "Do you ",
    "Is there ",
    "In one word",
)

# -------------------------------------------------
# 4️⃣ Helpers
# -------------------------------------------------
def extract_category_name(filename: str) -> str:
    name = os.path.splitext(filename)[0]
    name = CATEGORY_CLEAN_REGEX.sub("", name)
    return name.strip()


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
# 5️⃣ Process single document (returns summary)
# -------------------------------------------------
def process_document(doc_path: str, country):
    filename = os.path.basename(doc_path)
    category_name = extract_category_name(filename)

    print("\n" + "=" * 60)
    print(f"📄 File     : {filename}")
    print(f"📂 Category : {category_name}")
    print("=" * 60)

    category, _ = SurveyCategory.objects.get_or_create(
        name=category_name,
        defaults={"country": country, "order": 1}
    )

    doc = Document(doc_path)

    current_survey = None
    current_question = None
    option_buffer = []
    inside_section = False

    section_summary = {}
    total_questions = 0

    for para in doc.paragraphs:
        lines = [line.strip() for line in para.text.split("\n") if line.strip()]

        for text in lines:

            # Section
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
                section_summary[text] = 0
                continue

            if not inside_section:
                continue

            # Bullet option
            if text.startswith("*"):
                option_buffer.append(text)
                continue

            # Open text
            if "Open Text Field" in text:
                if current_question:
                    current_question.question_type = "text"
                    current_question.save(update_fields=["question_type"])
                continue

            # Question
            if is_question_line(text):
                save_choices(current_question, option_buffer)

                q_type = detect_question_type(text)

                current_question, _ = Question.objects.get_or_create(
                    question_text=text,
                    defaults={
                        "question_type": q_type,
                        "is_required": True
                    }
                )

                current_question.surveys.add(current_survey)
                option_buffer = []

                section_summary[current_survey.name] += 1
                total_questions += 1
                continue

            # Plain option
            option_buffer.append(text)

    save_choices(current_question, option_buffer)

    return {
        "category": category_name,
        "sections": section_summary,
        "total_questions": total_questions
    }


# -------------------------------------------------
# 6️⃣ Main controller (interactive)
# -------------------------------------------------
def import_from_directory(country_code: str, directory: str):
    print("\n🚀 INTERACTIVE SURVEY IMPORT STARTED")

    if not os.path.isdir(directory):
        raise RuntimeError(f"❌ Directory not found: {directory}")

    country = Country.objects.get(code=country_code)
    print(f"🌍 Country: {country}")

    files = sorted(f for f in os.listdir(directory) if f.lower().endswith(".docx"))

    if not files:
        print("⚠ No DOCX files found")
        return

    for file in files:
        doc_path = os.path.join(directory, file)

        with transaction.atomic():
            summary = process_document(doc_path, country)

            # ---- Print summary
            print("\n📊 IMPORT SUMMARY")
            print("-" * 40)
            for section, count in summary["sections"].items():
                print(f"{section:<45} : {count}")
            print("-" * 40)
            print(f"TOTAL QUESTIONS : {summary['total_questions']}")
            print("-" * 40)

            # ---- Confirmation
            user_input = input("👉 Confirm import for this document? (y/n): ").strip().lower()

            if user_input != "y":
                print("❌ Import cancelled. Rolling back this document.")
                raise RuntimeError("User aborted import")

            print("✅ Document committed successfully")

    print("\n🎉 ALL DOCUMENTS PROCESSED AND CONFIRMED")


# -------------------------------------------------
# 7️⃣ CLI
# -------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("❌ Usage: python script.py <COUNTRY_CODE> <DOCX_DIRECTORY>")
        sys.exit(1)

    import_from_directory(
        sys.argv[1].upper(),
        os.path.abspath(sys.argv[2])
    )
