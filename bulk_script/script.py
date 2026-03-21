import os
import sys
import django
import re
import json
from datetime import datetime, timezone
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

OPEN_TEXT_REGEX = re.compile(r"open\s*text", re.IGNORECASE)

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
    if not question or question.question_type != "single_choice":
        return

    for opt in options:
        Choice.objects.get_or_create(
            question=question,
            choice_text=clean_option(opt)
        )


# -------------------------------------------------
# 5️⃣ Process single document
# -------------------------------------------------
def process_document(doc_path: str, country):
    filename = os.path.basename(doc_path)
    category_name = extract_category_name(filename)
    print(f"\n📁 Processing file: {filename} | Extracted category: {category_name}")
    category, _ = SurveyCategory.objects.get_or_create(
        name=category_name,
        country=country,  # hardcoded to USA for now
        defaults={"country": country, "order": 1}
    )
    print(f"   Created category: {category.name} for country: {country.name}")
    print(f"   Category: {category.name} | Country: {category.country.name}")

    doc = Document(doc_path)

    current_survey = None
    current_question = None
    option_buffer = []
    inside_section = False

    section_summary = {}
    total_questions = 0

    for para in doc.paragraphs:
        lines = [l.strip() for l in para.text.split("\n") if l.strip()]

        for text in lines:

            # -------------------------
            # Section
            # -------------------------
            print(f"   Processing line: {text}")  # Debug: show first 50 chars of line
            if SECTION_REGEX.match(text):
                print(f"\n📂 Detected Section: {text}")  # Debug: show detected section
                save_choices(current_question, option_buffer)
                option_buffer = []
                # print(f"\n📂 Processing Section: {text}")
                current_survey, _ = Survey.objects.get_or_create(
                    name=text,
                    category=category,
                    defaults={"is_active": True}
                )
                # print(f"   Created survey: {current_survey.name}")

                inside_section = True
                current_question = None
                section_summary[text] = 0
                continue

            if not inside_section:
                continue

            # -------------------------
            # Open text option (KEY FIX)
            # -------------------------
            if OPEN_TEXT_REGEX.search(text):
                if current_question:
                    current_question.question_type = "text"
                    current_question.save(update_fields=["question_type"])
                option_buffer = []  # discard any options
                continue

            # -------------------------
            # Bullet option
            # -------------------------
            if text.startswith("*"):
                option_buffer.append(text)
                continue

            # -------------------------
            # Question
            # -------------------------
            if is_question_line(text):
                save_choices(current_question, option_buffer)
                option_buffer = []

                q_type = detect_question_type(text)

                current_question, _ = Question.objects.get_or_create(
                    question_text=text,
                    defaults={
                        "question_type": q_type,
                        "is_required": True
                    }
                )

                # Ensure correct type on re-run
                if current_question.question_type != q_type:
                    current_question.question_type = q_type
                    current_question.save(update_fields=["question_type"])

                current_question.surveys.add(current_survey)

                section_summary[current_survey.name] += 1
                total_questions += 1
                continue

            # -------------------------
            # Plain option
            # -------------------------
            option_buffer.append(text)

    save_choices(current_question, option_buffer)

    return category_name, section_summary, total_questions


# -------------------------------------------------
# 6️⃣ Main controller with report
# -------------------------------------------------
def import_from_directory(country_code: str, directory: str):
    country = Country.objects.get(code=country_code)
    print(f"🚀 Starting import for country: {country.name} from directory: {directory}")

    report = {
        "country": country_code,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "documents": []
    }

    report_file = f"import_report_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

    files = sorted(f for f in os.listdir(directory) if f.lower().endswith(".docx"))

    for file in files:
        doc_path = os.path.join(directory, file)
        record = {"file": file}

        # try:
        with transaction.atomic():
            category, sections, total = process_document(doc_path, country)

            record.update({
                "category": category,
                "sections": sections,
                "total_questions": total
            })

            print("\n📊 IMPORT SUMMARY")
            for s, c in sections.items():
                print(f"{s:<45} : {c}")
            print(f"TOTAL QUESTIONS : {total}")

            # confirm = input("👉 Confirm import for this document? (y/n): ").strip().lower()
            # record["user_confirmed"] = confirm == "y"
            record["user_confirmed"] = True
            confirm = "y"  # auto-confirm for now

            if confirm != "y":
                record["status"] = "rolled_back"
                raise RuntimeError("User aborted")

            record["status"] = "committed"

        # except Exception:
        #     record.setdefault("status", "rolled_back")

        report["documents"].append(record)

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print(f"\n📄 Import report saved to: {report_file}")


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
