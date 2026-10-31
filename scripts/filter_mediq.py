"""Automated Dataset Acquisition, Filtering & Schema Extraction for MEDIQ.

Outputs: data/enhanced_hospital_faq.json
Contains structured customer-receptionist interactions, administrative FAQs,
and appointment scheduling Q&A pairs in English, Hindi, and Hinglish.
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

# Paths
BASE_DIR = Path(__file__).resolve().parents[1]
MEDIQ_DIR = BASE_DIR / "mediq_data"
DAILY_DIR = MEDIQ_DIR / "data" / "daily"
OUTPUT_FILE = BASE_DIR / "data" / "enhanced_hospital_faq.json"

ZENODO_ZIP_URL = "https://zenodo.org/records/19204472/files/ProxyAyush/MEDIQ-v0.6.0.zip"
GITHUB_ZIP_URL = "https://github.com/ProxyAyush/MEDIQ/archive/refs/tags/v0.6.0.zip"

# Greetings and pleasantries to filter out
GREETING_WORDS = {
    "hi", "hello", "hey", "hii", "hiii", "helloo",
    "thanks", "thank you", "thankyou", "thx", "dhanyawad",
    "ok", "okay", "k", "bye", "goodbye",
    "namaste", "pranam", "radhe radhe", "jai shree ram",
    "good morning", "good afternoon", "good evening", "good night",
    "kaise ho", "kese ho", "help", "test"
}

# Academic categories and keywords to filter out
ACADEMIC_CATEGORIES = {
    "admissions", "exams", "courses", "career", "faculty", "fees", "research"
}

ACADEMIC_KEYWORDS = [
    "admission", "admissions", "entrance", "mphil", "bmlt", "mbbs", "bds", "neet",
    "syllabus", "cutoff", "cut off", "scholarship", "hostel", "course fee",
    "semester", "internship vacancy", "non pg jr", "junior resident", "senior resident vacancy",
    "caship", "result", "marksheet", "recruitment", "job vacancy", "phd", "md entrance",
    "fellowship", "convocation", "admit card", "answer key", "counselling", "allotment",
    "seat matrix", "degree certificate", "library book", "mru", "dhr"
]

# Medical diagnosis and self-treatment queries to filter out
DIAGNOSIS_TREATMENT_PATTERNS = [
    r"\bsymptoms?\s+of\b",
    r"\btreatment\s+(for|of)\b",
    r"\bhow\s+to\s+treat\b",
    r"\bhome\s+remed(y|ies)\b",
    r"\bcure\s+(for|of)\b",
    r"\bcauses?\s+of\b",
    r"\bcan\s+you\s+diagnose\b",
    r"\bdiagnose\s+(me|my)\b",
    r"\bdawai\s+(batao|bataiye|de do|chahiye)\b",
    r"\bdawa\s+(batao|bataiye|chahiye)\b",
    r"\bilaj\s+(batao|bataiye|kaise kare)\b",
    r"\blakshan\s+kya\s+hai\b",
    r"\bbimari\s+ka\s+ilaj\b",
    r"\bwhat\s+medicine\s+should\s+i\s+take\b",
    r"\bwhich\s+tablet\s+for\b",
    r"\bhomeopathic\s+cure\b",
]
DIAGNOSIS_REGEX = re.compile("|".join(DIAGNOSIS_TREATMENT_PATTERNS), re.IGNORECASE)

# Hospital department names for topic tag classification
DEPARTMENT_KEYWORDS = {
    "department", "departments", "cardiology", "neurology", "orthopedics",
    "ortho", "pediatrics", "dermatology", "derma", "ent", "radiology",
    "pathology", "psychiatry", "urology", "nephrology", "gastroenterology",
    "gastro", "pulmonology", "oncology", "surgical", "surgery", "internal medicine",
    "medicine opd", "ophthalmology", "eye", "gynecology", "gynaecology", "obstetrics",
    "gynae", "dental", "ayush", "rheumatology", "endocrinology", "hematology",
    "icu", "emergency", "trauma", "casualty", "blood bank", "ward"
}

# Mapping for ai_intent to exact schema values
INTENT_MAPPING = {
    "scheduling": "Scheduling",
    "information_seeking": "information seeking",
    "navigation": "navigation"
}

# Mapping for ai_language to exact schema values
LANGUAGE_MAPPING = {
    "en": "English",
    "hi": "Hindi",
    "hi-en": "hi-en (Hinglish)",
    "hi-latn": "hi-en (Hinglish)",
    "hi-latn-en": "hi-en (Hinglish)",
    "en-hi": "hi-en (Hinglish)",
    "en-hi-latn": "hi-en (Hinglish)"
}


def acquire_mediq_dataset() -> Path:
    """Ensure MEDIQ daily logs are present on disk.

    Acquisition priority:
    1. Existing local directory mediq_data/data/daily
    2. Local zip archives (*MEDIQ*.zip)
    3. Programmatic download from Zenodo / GitHub release
    4. Local git history archive fallback (offline / sandboxed mode)
    """
    if DAILY_DIR.exists() and any(DAILY_DIR.glob("*.json")):
        print(f"Found existing MEDIQ daily logs in {DAILY_DIR}")
        return DAILY_DIR

    # 2. Check local zip archives
    local_zips = list(BASE_DIR.glob("*MEDIQ*.zip")) + list(MEDIQ_DIR.glob("*.zip"))
    for zip_path in local_zips:
        try:
            print(f"Extracting local archive {zip_path.name}...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(MEDIQ_DIR)
            found = list(MEDIQ_DIR.rglob("daily"))
            if found:
                return found[0]
        except Exception as e:
            print(f"Warning: Failed extracting {zip_path}: {e}", file=sys.stderr)

    # 3. Attempt programmatic download from Zenodo / GitHub
    for url in [ZENODO_ZIP_URL, GITHUB_ZIP_URL]:
        try:
            print(f"Attempting download from {url}...")
            req = urllib.request.Request(url, headers={"User-Agent": "MEDIQ-Voice-Assistant/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read()
                print(f"Downloaded {len(content)} bytes. Extracting...")
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    zf.extractall(MEDIQ_DIR)
                found = list(MEDIQ_DIR.rglob("daily"))
                if found:
                    return found[0]
        except Exception as e:
            print(f"Download from {url} failed: {e}", file=sys.stderr)

    # 4. Fallback: Extract from local git history if offline/sandboxed
    print("Extracting MEDIQ daily dataset from local git archive...")
    try:
        res = subprocess.run(
            ["git", "archive", "--format=tar", "be6415d^", "mediq_data/data/daily"],
            cwd=BASE_DIR,
            capture_output=True,
            check=True
        )
        with tarfile.open(fileobj=io.BytesIO(res.stdout)) as tf:
            tf.extractall(BASE_DIR)
        if DAILY_DIR.exists() and any(DAILY_DIR.glob("*.json")):
            print(f"Successfully extracted {len(list(DAILY_DIR.glob('*.json')))} daily logs from git tree.")
            return DAILY_DIR
    except Exception as e:
        print(f"Git archive extraction failed: {e}", file=sys.stderr)

    raise RuntimeError("Could not acquire MEDIQ dataset through local files, Zenodo download, or git history.")


def clean_spoken_answer(answer: str) -> str:
    """Clean markdown links and formatting so answers are concise and spoken-friendly."""
    if not answer:
        return ""
    # Replace Indian Rupee symbol with 'Rupees ' for spoken TTS clarity & encoding safety
    cleaned = answer.replace("\u20b9", "Rupees ")
    # Replace markdown links [Anchor Text](url) with Anchor Text
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # Remove raw URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    # Remove bullet asterisks or dashes at start of lines
    cleaned = re.sub(r"^\s*[\*\-]\s+", "", cleaned, flags=re.MULTILINE)
    # Remove markdown bold/italics markers
    cleaned = re.sub(r"[\*_]{1,3}", "", cleaned)
    # Replace multiple whitespaces / newlines with single spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_greeting(question: str, intent: str) -> bool:
    """Check if query is a greeting or pleasantry."""
    if intent == "greeting":
        return True
    cleaned = question.strip().lower()
    cleaned_no_punct = re.sub(r"[^\w\s]", "", cleaned).strip()
    if cleaned_no_punct in GREETING_WORDS:
        return True
    words = cleaned_no_punct.split()
    if len(words) <= 1 and (not words or words[0] in GREETING_WORDS):
        return True
    return False


def is_academic_query(category: str, question: str, tags: str) -> bool:
    """Check if query relates to university academics or exams."""
    if category in ACADEMIC_CATEGORIES:
        return True
    q_low = question.lower()
    if any(k in q_low for k in ACADEMIC_KEYWORDS):
        return True
    if tags:
        tag_parts = [t.strip().lower() for t in tags.split(";")]
        if any(t in {"admission", "exam", "course", "placement", "faculty", "career", "recruitment"} for t in tag_parts):
            return True
    return False


def is_medical_diagnosis_query(question: str) -> bool:
    """Check if query asks for medical diagnosis, symptoms, or self-treatment."""
    return bool(DIAGNOSIS_REGEX.search(question))


def classify_topic(category: str, tags: str, question: str) -> Optional[str]:
    """Classify query into one of: 'OPD', 'timing', 'appointment', 'departments'."""
    tag_set = {t.strip().lower() for t in tags.split(";")} if tags else set()
    q_low = question.lower()

    # 1. Timing queries (OPD timings, doctor timings, visit hours)
    timing_keywords = ["timing", "timings", "hours", "schedule", "time", "samay", "kab khulta", "kab baithte", "kis din", "kab band"]
    if "timing" in tag_set or "timings" in tag_set or any(k in q_low for k in timing_keywords):
        return "timing"

    # 2. OPD queries (OPD registration, counters, ticket, location)
    if "opd" in tag_set or category == "opd" or "opd" in q_low:
        return "OPD"

    # 3. Appointment queries (booking, scheduling, slots, tokens)
    appointment_keywords = ["appointment", "booking", "book", "slot", "parcha", "पर्चा", "मिलना है", "dikhana hai", "dikha sakte"]
    if "appointment" in tag_set or "booking" in tag_set or category == "appointment" or any(k in q_low for k in appointment_keywords):
        return "appointment"

    # 4. Department queries (clinical specialties, wards, doctor consultation)
    if (
        category == "departments"
        or tag_set.intersection(DEPARTMENT_KEYWORDS)
        or any(d in q_low for d in DEPARTMENT_KEYWORDS)
    ):
        return "departments"

    return None


def extract_enhanced_faq() -> List[Dict[str, Any]]:
    """Parse daily logs, filter irrelevant queries, and structure hospital FAQ records."""
    daily_dir = acquire_mediq_dataset()
    print(f"Reading MEDIQ daily logs from: {daily_dir}")
    daily_files = sorted(list(daily_dir.glob("*.json")))
    print(f"Found {len(daily_files)} daily JSON files.")

    all_entries = []
    session_counts: Dict[str, int] = {}

    for file_path in daily_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                entries = data.get("entries", [])
                for entry in entries:
                    sid = entry.get("session_id")
                    if sid:
                        session_counts[sid] = session_counts.get(sid, 0) + 1
                all_entries.extend(entries)
        except Exception as e:
            print(f"Warning: Failed reading {file_path.name}: {e}", file=sys.stderr)

    print(f"Loaded {len(all_entries)} total raw entries. Processing filtering...")
    df = pd.DataFrame(all_entries)

    filtered_records: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        question = str(row.get("question", "")).strip()
        if not question or len(question) < 3:
            continue

        raw_answer = str(row.get("answer", "")).strip()
        category = str(row.get("category", "")).strip().lower()
        intent_raw = str(row.get("ai_intent", "")).strip().lower()
        tags_raw = str(row.get("ai_topic_tags", "")).strip()
        lang_raw = str(row.get("ai_language", "")).strip().lower()
        requires_followup = bool(row.get("ai_requires_followup", False))
        session_id = str(row.get("session_id", ""))
        is_followup = bool(row.get("is_followup", False))

        # Filter 1: Greetings
        if is_greeting(question, intent_raw):
            continue

        # Filter 2: Irrelevant academic queries
        if is_academic_query(category, question, tags_raw):
            continue

        # Filter 3: Medical diagnosis / treatment queries
        if is_medical_diagnosis_query(question):
            continue

        # Validate & Map Intent
        intent = INTENT_MAPPING.get(intent_raw)
        if not intent:
            continue

        # Validate & Map Language
        language = LANGUAGE_MAPPING.get(lang_raw)
        if not language:
            continue

        # Validate & Classify Topic Tag
        topic_tag = classify_topic(category, tags_raw, question)
        if not topic_tag:
            continue

        # Identify multi-turn exchanges
        is_multi_turn = is_followup or (session_id and session_counts.get(session_id, 0) > 1)

        # Clean answer text for spoken delivery
        spoken_answer = clean_spoken_answer(raw_answer)

        # Structured output schema matching specification
        filtered_records.append({
            "question": question,
            "answer": spoken_answer,
            "ai_language": language,
            "ai_intent": intent,
            "ai_topic_tags": topic_tag,
            "ai_requires_followup": requires_followup,
            "is_multi_turn": is_multi_turn,
            "session_id": session_id if session_id else None
        })

    # Convert to DataFrame for deduplication and analysis
    result_df = pd.DataFrame(filtered_records)
    initial_count = len(result_df)
    # Deduplicate exact question matches
    result_df = result_df.drop_duplicates(subset=["question"]).reset_index(drop=True)
    dedup_count = len(result_df)

    print(f"Filtered records: {initial_count} (Unique questions: {dedup_count})")
    print("\n--- Distribution Breakdown ---")
    print("Languages:\n", result_df["ai_language"].value_counts())
    print("\nIntents:\n", result_df["ai_intent"].value_counts())
    print("\nTopic Tags:\n", result_df["ai_topic_tags"].value_counts())
    print("\nRequires Follow-up:\n", result_df["ai_requires_followup"].value_counts())
    print("\nMulti-turn Exchanges:\n", result_df["is_multi_turn"].value_counts())

    output_list = result_df.to_dict(orient="records")

    # Save to data/enhanced_hospital_faq.json
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_list, f, indent=2, ensure_ascii=False)

    print(f"\nSuccessfully saved {len(output_list)} structured records to {OUTPUT_FILE}")
    return output_list


if __name__ == "__main__":
    extract_enhanced_faq()
