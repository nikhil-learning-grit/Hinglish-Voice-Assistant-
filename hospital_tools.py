# hospital_tools.py
"""Utility module for the Hinglish Voice Assistant.
Provides simple, deterministic access to hospital information and
appointment management using the mock JSON data created in Phase 1.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Base directory of the project (where this file resides)
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

# Cached data (loaded once per interpreter session)
_hospital_data: Optional[Dict[str, Any]] = None
_doctors_data: Optional[List[Dict[str, Any]]] = None
_appointments_data: Optional[List[Dict[str, Any]]] = None


def _load_json(file_name: str) -> Any:
    """Load a JSON file from the data directory.
    Cached after the first read for performance.
    """
    path = DATA_DIR / file_name
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _ensure_data_loaded() -> None:
    """Populate the module‑level caches if they are still empty."""
    global _hospital_data, _doctors_data, _appointments_data
    if _hospital_data is None:
        _hospital_data = _load_json("hospital.json")
    if _doctors_data is None:
        _doctors_data = _load_json("doctors.json")
    if _appointments_data is None:
        _appointments_data = _load_json("appointments.json")


def _save_appointments() -> None:
    """Write the in‑memory appointments list back to the JSON file.
    Uses an atomic replace to avoid corrupting the file on failure.
    """
    path = DATA_DIR / "appointments.json"
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fp:
        json.dump(_appointments_data, fp, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hospital_information(topic: str) -> Dict[str, Any]:
    """Return information from *hospital.json* based on a free‑form *topic*.

    Supported topics (case‑insensitive) include:
      * ``departments`` – list of department dictionaries
      * ``timings`` / ``operating_hours`` – operating hour sections
      * ``location`` – address and landmark details
      * ``faqs`` – the list of FAQ entries
      * ``contact`` – phone, email, website, emergency helpline
    If the topic is unknown, a helpful message is returned.
    """
    _ensure_data_loaded()
    topic_key = topic.strip().lower()

    # Mapping of known topics to the JSON keys they expose
    topic_map = {
        "departments": _hospital_data.get("departments"),
        "timings": _hospital_data.get("operating_hours"),
        "operating_hours": _hospital_data.get("operating_hours"),
        "location": _hospital_data.get("location"),
        "address": _hospital_data.get("location"),
        "faqs": _hospital_data.get("faqs"),
        "contact": _hospital_data.get("contact"),
        "policies": _hospital_data.get("appointment_policies"),
    }

    result = topic_map.get(topic_key)
    if result is None:
        return {
            "success": False,
            "message": f"Topic '{topic}' not recognised. Available topics: {', '.join(sorted(topic_map))}.",
        }
    return {"success": True, "data": result}


def get_available_slots(specialization: str, date: str) -> Dict[str, Any]:
    """Return a mapping of doctor names → free time slots on *date*.

    Parameters
    ----------
    specialization: str
        e.g. ``"General Medicine"`` or ``"Cardiology"`` (case‑insensitive).
    date: str
        ISO‑format date string (``YYYY‑MM‑DD``).
    """
    _ensure_data_loaded()
    spec_norm = specialization.strip().lower()
    # Find doctors matching the specialization
    matching_doctors = [d for d in _doctors_data if d.get("specialization", "").lower() == spec_norm]
    if not matching_doctors:
        return {"success": False, "message": f"No doctors found for specialization '{specialization}'."}

    # Build a dict doctor_name -> list of free slots
    slots_by_doctor: Dict[str, List[str]] = {}
    for doc in matching_doctors:
        doctor_id = doc["doctor_id"]
        doctor_name = doc["name"]
        free_slots = [
            appt["time_slot"]
            for appt in _appointments_data
            if appt["doctor_id"] == doctor_id
            and appt["date"] == date
            and appt["status"] == "available"
        ]
        if free_slots:
            slots_by_doctor[doctor_name] = free_slots
    if not slots_by_doctor:
        return {"success": False, "message": f"No available slots on {date} for {specialization}."}
    return {"success": True, "data": slots_by_doctor}


def book_appointment(
    patient_name: str,
    specialization: str,
    date: str,
    time_slot: str,
    patient_phone: str = "",
    reason_for_visit: str = "",
) -> Dict[str, Any]:
    """Attempt to book an appointment.

    Returns a dictionary with the keys:
        * ``success`` – ``True`` if the booking succeeded.
        * ``message`` – human‑readable description.
        * ``booking`` – present only on success; contains the new appointment record.
    """
    _ensure_data_loaded()

    # Basic validation
    if not all([patient_name.strip(), specialization.strip(), date.strip(), time_slot.strip()]):
        return {"success": False, "message": "All fields (patient name, specialization, date, time slot) are required."}

    spec_norm = specialization.strip().lower()
    # Find a doctor with the required specialization who has the exact slot available
    candidate_doctors = [d for d in _doctors_data if d.get("specialization", "").lower() == spec_norm]
    if not candidate_doctors:
        return {"success": False, "message": f"No doctors found for specialization '{specialization}'."}

    chosen_doctor = None
    for doc in candidate_doctors:
        doctor_id = doc["doctor_id"]
        for appt in _appointments_data:
            if (
                appt["doctor_id"] == doctor_id
                and appt["date"] == date
                and appt["time_slot"] == time_slot
                and appt["status"] == "available"
            ):
                chosen_doctor = (doc, appt)
                break
        if chosen_doctor:
            break

    if not chosen_doctor:
        return {"success": False, "message": f"Requested slot {time_slot} on {date} is not available for specialization '{specialization}'."}

    doctor, slot_record = chosen_doctor

    # Create a unique appointment ID – keep numeric order for readability
    existing_ids = [int(a["appointment_id"].split("-")[1]) for a in _appointments_data if a["appointment_id"].startswith("APT-")]
    next_id_num = max(existing_ids, default=1000) + 1
    new_id = f"APT-{next_id_num:04d}"

    # Build the new appointment entry
    new_appointment = {
        "appointment_id": new_id,
        "doctor_id": doctor["doctor_id"],
        "doctor_name": doctor["name"],
        "specialization": doctor["specialization"],
        "date": date,
        "time_slot": time_slot,
        "status": "booked",
        "patient": {
            "patient_id": f"PAT-{uuid.uuid4().hex[:6].upper()}",
            "name": patient_name,
            "phone": patient_phone,
            "gender": "",
            "age": None,
        },
        "reason_for_visit": reason_for_visit or None,
        "booking_timestamp": datetime.now().isoformat(),
        "consultation_fee": doctor.get("consultation_fee", 0),
    }

    # Replace the old slot record with the booked one
    slot_index = _appointments_data.index(slot_record)
    _appointments_data[slot_index] = new_appointment
    # Persist the change
    _save_appointments()

    return {
        "success": True,
        "message": f"Appointment booked with {doctor['name']} on {date} at {time_slot}.",
        "booking": new_appointment,
    }

# ---------------------------------------------------------------------------
# Simple self‑test (executed only when the module is run directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Demonstrate each function with deterministic sample data
    print(get_hospital_information("departments"))
    print(get_available_slots("General Medicine", "2026-11-02"))
    print(
        book_appointment(
            patient_name="Test User",
            specialization="General Medicine",
            date="2026-11-02",
            time_slot="10:00 AM",
            patient_phone="+91-99999-88888",
            reason_for_visit="Routine check",
        )
    )
