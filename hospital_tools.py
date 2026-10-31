# hospital_tools.py
"""Utility module for the Hinglish Voice Assistant.
Provides robust, deterministic access to hospital information and
appointment management using the mock JSON data in the data/ directory.
"""

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Base directory of the project (where this file resides)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Thread lock to prevent race conditions during booking
_BOOKING_LOCK = threading.Lock()

# Cached data (loaded once per interpreter session or reloaded)
_hospital_data: Optional[Dict[str, Any]] = None
_doctors_data: Optional[List[Dict[str, Any]]] = None
_appointments_data: Optional[List[Dict[str, Any]]] = None


def _load_json(file_name: str) -> Any:
    """Load a JSON file from the data directory."""
    path = DATA_DIR / file_name
    if not path.exists():
        raise FileNotFoundError(f"Data file '{file_name}' not found at {path}")
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _ensure_data_loaded(force_reload: bool = False) -> None:
    """Populate the module-level caches if empty or if force_reload is True."""
    global _hospital_data, _doctors_data, _appointments_data
    if force_reload or _hospital_data is None:
        _hospital_data = _load_json("hospital.json")
    if force_reload or _doctors_data is None:
        _doctors_data = _load_json("doctors.json")
    if force_reload or _appointments_data is None:
        _appointments_data = _load_json("appointments.json")


def reload_data() -> None:
    """Force reload data from disk into memory caches."""
    _ensure_data_loaded(force_reload=True)


def _save_appointments() -> bool:
    """Write the in-memory appointments list back to the JSON file atomically."""
    path = DATA_DIR / "appointments.json"
    tmp_path = path.with_suffix(".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(_appointments_data, fp, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
        return True
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hospital_information(topic: str) -> Dict[str, Any]:
    """Retrieve hospital information based on a topic or query.

    Supported topics:
      - 'departments': List of departments and services
      - 'timings' / 'operating_hours': OPD, emergency, pharmacy timings
      - 'location' / 'address': Address, area, landmarks
      - 'faqs': Complete list of frequently asked questions
      - 'contact': Phone, email, emergency helpline
      - 'policies': Appointment and visit policies
      - Specific FAQ queries or keywords (e.g., 'OPD timings', 'emergency at night')

    Returns a structured dictionary:
      {"success": bool, "message": str, "data": Any}
    """
    _ensure_data_loaded()

    if not topic or not isinstance(topic, str) or not topic.strip():
        return {
            "success": False,
            "message": "A valid query topic string must be provided.",
            "data": None,
        }

    topic_clean = topic.strip().lower()

    # Direct top-level topic mapping
    topic_map = {
        "departments": _hospital_data.get("departments"),
        "department": _hospital_data.get("departments"),
        "timings": _hospital_data.get("operating_hours"),
        "operating_hours": _hospital_data.get("operating_hours"),
        "hours": _hospital_data.get("operating_hours"),
        "location": _hospital_data.get("location"),
        "address": _hospital_data.get("location"),
        "faqs": _hospital_data.get("faqs"),
        "faq": _hospital_data.get("faqs"),
        "contact": _hospital_data.get("contact"),
        "phone": _hospital_data.get("contact"),
        "helpline": _hospital_data.get("contact"),
        "policies": _hospital_data.get("appointment_policies"),
        "appointment_policies": _hospital_data.get("appointment_policies"),
        "name": _hospital_data.get("name"),
        "hospital_name": _hospital_data.get("name"),
    }

    if topic_clean in topic_map:
        return {
            "success": True,
            "message": f"Information retrieved successfully for topic '{topic.strip()}'.",
            "data": topic_map[topic_clean],
        }

    # Search through FAQs for matching questions or keywords
    faqs = _hospital_data.get("faqs", [])
    matched_faqs = []
    for faq in faqs:
        q_en = faq.get("question", "").lower()
        q_hi = faq.get("question_hinglish", "").lower()
        keywords = [k.lower() for k in faq.get("keywords", [])]

        if (
            topic_clean in q_en
            or topic_clean in q_hi
            or any(k in topic_clean for k in keywords)
            or any(topic_clean in k for k in keywords)
        ):
            matched_faqs.append(faq)

    if matched_faqs:
        return {
            "success": True,
            "message": f"Found {len(matched_faqs)} relevant FAQ(s) for '{topic.strip()}'.",
            "data": matched_faqs if len(matched_faqs) > 1 else matched_faqs[0],
        }

    # Safe fallback response without hallucinations
    return {
        "success": False,
        "message": (
            f"No verified information found for '{topic.strip()}'. "
            "Please call our 24/7 helpdesk at +91-11-2659-4000 or inquire at the reception."
        ),
        "data": None,
    }


def get_available_slots(specialization: str, date: str) -> Dict[str, Any]:
    """Return available (unbooked) appointment time slots for a specialization on a given date.

    Parameters:
      - specialization: Medical department/specialization (e.g. 'General Medicine', 'Cardiology')
      - date: Date string in 'YYYY-MM-DD' format

    Returns a structured dictionary:
      {"success": bool, "message": str, "data": Dict[str, List[str]] | None}
    """
    _ensure_data_loaded()

    if not specialization or not isinstance(specialization, str) or not specialization.strip():
        return {
            "success": False,
            "message": "Specialization must be provided as a non-empty string.",
            "data": None,
        }

    if not date or not isinstance(date, str) or not date.strip():
        return {
            "success": False,
            "message": "Date must be provided as a non-empty string in YYYY-MM-DD format.",
            "data": None,
        }

    date_str = date.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {
            "success": False,
            "message": f"Invalid date format '{date}'. Expected YYYY-MM-DD.",
            "data": None,
        }

    spec_clean = specialization.strip().lower()

    # Find matching doctors
    matching_doctors = [
        d for d in _doctors_data
        if d.get("specialization", "").strip().lower() == spec_clean
    ]

    if not matching_doctors:
        available_specs = sorted(list({d.get("specialization") for d in _doctors_data if d.get("specialization")}))
        return {
            "success": False,
            "message": (
                f"No doctors found for specialization '{specialization.strip()}'. "
                f"Available specializations: {', '.join(available_specs)}."
            ),
            "data": None,
        }

    # Build mapping of Doctor Name -> available slots
    slots_by_doctor: Dict[str, List[str]] = {}
    for doc in matching_doctors:
        doc_id = doc["doctor_id"]
        doc_name = doc["name"]

        # Only look for slots if the doctor has schedule for this date
        if date_str not in doc.get("available_dates", []):
            continue

        free_slots = [
            appt["time_slot"]
            for appt in _appointments_data
            if appt.get("doctor_id") == doc_id
            and appt.get("date") == date_str
            and appt.get("status") == "available"
        ]

        if free_slots:
            slots_by_doctor[doc_name] = sorted(free_slots)

    if not slots_by_doctor:
        return {
            "success": False,
            "message": f"No available appointment slots found for '{specialization.strip()}' on {date_str}.",
            "data": {},
        }

    total_slots = sum(len(s) for s in slots_by_doctor.values())
    return {
        "success": True,
        "message": f"Found {total_slots} available slot(s) across {len(slots_by_doctor)} doctor(s) for {specialization.strip()} on {date_str}.",
        "data": slots_by_doctor,
    }


def book_appointment(
    patient_name: str,
    specialization: str,
    date: str,
    time_slot: str,
    patient_phone: str = "",
    reason_for_visit: str = "",
) -> Dict[str, Any]:
    """Book an appointment for a patient in an available slot.

    Parameters:
      - patient_name: Full name of the patient
      - specialization: Medical department/specialization
      - date: Date string in 'YYYY-MM-DD' format
      - time_slot: Appointment time (e.g. '10:00 AM')
      - patient_phone: Contact phone number (optional)
      - reason_for_visit: Reason or symptoms (optional)

    Returns a structured dictionary:
      {
        "success": bool,
        "message": str,
        "data": {
            "booking_reference": str,
            "appointment": dict
        } | None,
        "booking_reference": str | None,
        "booking": dict | None
      }
    """
    _ensure_data_loaded()

    # Validate inputs
    if not patient_name or not isinstance(patient_name, str) or not patient_name.strip():
        return {
            "success": False,
            "message": "Patient name is required and cannot be empty.",
            "data": None,
            "booking_reference": None,
            "booking": None,
        }

    if not specialization or not isinstance(specialization, str) or not specialization.strip():
        return {
            "success": False,
            "message": "Specialization is required and cannot be empty.",
            "data": None,
            "booking_reference": None,
            "booking": None,
        }

    if not date or not isinstance(date, str) or not date.strip():
        return {
            "success": False,
            "message": "Date is required and cannot be empty.",
            "data": None,
            "booking_reference": None,
            "booking": None,
        }

    date_str = date.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return {
            "success": False,
            "message": f"Invalid date format '{date}'. Expected YYYY-MM-DD.",
            "data": None,
            "booking_reference": None,
            "booking": None,
        }

    if not time_slot or not isinstance(time_slot, str) or not time_slot.strip():
        return {
            "success": False,
            "message": "Time slot is required and cannot be empty.",
            "data": None,
            "booking_reference": None,
            "booking": None,
        }

    time_slot_str = time_slot.strip()
    spec_clean = specialization.strip().lower()

    with _BOOKING_LOCK:
        # Match doctors by specialization
        matching_doctors = [
            d for d in _doctors_data
            if d.get("specialization", "").strip().lower() == spec_clean
        ]

        if not matching_doctors:
            available_specs = sorted(list({d.get("specialization") for d in _doctors_data if d.get("specialization")}))
            return {
                "success": False,
                "message": (
                    f"Invalid specialization '{specialization.strip()}'. "
                    f"Available specializations: {', '.join(available_specs)}."
                ),
                "data": None,
                "booking_reference": None,
                "booking": None,
            }

        matching_doc_ids = {d["doctor_id"]: d for d in matching_doctors}

        # Check existing appointment slot
        target_slot = None
        target_index = None

        for idx, appt in enumerate(_appointments_data):
            if (
                appt.get("doctor_id") in matching_doc_ids
                and appt.get("date") == date_str
                and appt.get("time_slot", "").strip().lower() == time_slot_str.lower()
            ):
                target_slot = appt
                target_index = idx
                break

        if not target_slot:
            return {
                "success": False,
                "message": (
                    f"No schedule found for {specialization.strip()} on {date_str} at {time_slot_str}. "
                    "Please check available slots first."
                ),
                "data": None,
                "booking_reference": None,
                "booking": None,
            }

        if target_slot.get("status") != "available":
            return {
                "success": False,
                "message": (
                    f"The requested slot on {date_str} at {time_slot_str} with {target_slot.get('doctor_name')} "
                    f"is already booked. Please choose an alternative slot."
                ),
                "data": None,
                "booking_reference": None,
                "booking": None,
            }

        # Booking is valid! Generate unique booking reference and appointment ID
        doctor = matching_doc_ids[target_slot["doctor_id"]]
        booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"

        existing_nums = []
        for a in _appointments_data:
            aid = a.get("appointment_id", "")
            if aid.startswith("APT-") and aid[4:].isdigit():
                existing_nums.append(int(aid[4:]))
        next_num = max(existing_nums, default=1000) + 1
        new_appointment_id = f"APT-{next_num:04d}"

        updated_appointment = {
            "appointment_id": new_appointment_id,
            "doctor_id": doctor["doctor_id"],
            "doctor_name": doctor["name"],
            "specialization": doctor["specialization"],
            "date": date_str,
            "time_slot": target_slot["time_slot"],
            "status": "booked",
            "booking_reference": booking_ref,
            "patient": {
                "patient_id": f"PAT-{uuid.uuid4().hex[:6].upper()}",
                "name": patient_name.strip(),
                "phone": patient_phone.strip() if patient_phone else None,
                "gender": "",
                "age": None,
            },
            "reason_for_visit": reason_for_visit.strip() if reason_for_visit else "Consultation",
            "booking_timestamp": datetime.now().isoformat(),
            "consultation_fee": doctor.get("consultation_fee", 600),
        }

        # Atomic in-memory update and save
        _appointments_data[target_index] = updated_appointment
        _save_appointments()

        return {
            "success": True,
            "message": (
                f"Appointment successfully confirmed with {doctor['name']} for {patient_name.strip()} "
                f"on {date_str} at {target_slot['time_slot']}. Booking Reference: {booking_ref}."
            ),
            "data": {
                "booking_reference": booking_ref,
                "appointment": updated_appointment,
            },
            "booking_reference": booking_ref,
            "booking": updated_appointment,
        }
