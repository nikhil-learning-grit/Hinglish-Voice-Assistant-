# tests/test_hospital.py
"""Test suite for hospital_tools backend module.

Validates core scenarios:
1. Valid appointment booking with unique reference generation.
2. Rejection of already-booked or unavailable slots.
3. Input validation errors (missing patient names, invalid specializations, bad dates).
4. Safe, un-fabricated handling of unknown FAQ and hospital queries.
5. Prevention of double-booking under sequential and concurrent attempts.
6. Consistent structured dictionary contract: {"success": bool, "message": str, "data": Any}.
"""

import concurrent.futures
import json
import os
import shutil
import unittest
from pathlib import Path

import hospital_tools
from hospital_tools import (
    DATA_DIR,
    book_appointment,
    get_available_slots,
    get_hospital_information,
    reload_data,
)


class TestHospitalTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.appointments_file = DATA_DIR / "appointments.json"
        with open(cls.appointments_file, "r", encoding="utf-8") as f:
            cls.original_appointments_content = f.read()

    @classmethod
    def tearDownClass(cls):
        with open(cls.appointments_file, "w", encoding="utf-8") as f:
            f.write(cls.original_appointments_content)
        reload_data()

    def setUp(self):
        # Reset appointments.json and in-memory cache to original state before each test
        with open(self.appointments_file, "w", encoding="utf-8") as f:
            f.write(self.original_appointments_content)
        reload_data()

    def tearDown(self):
        # Clean up any changes after each test
        with open(self.appointments_file, "w", encoding="utf-8") as f:
            f.write(self.original_appointments_content)
        reload_data()

    # -----------------------------------------------------------------------
    # 1. Hospital Information & FAQ Tests
    # -----------------------------------------------------------------------

    def test_get_hospital_information_standard_topics(self):
        """Test retrieving standard hospital info topics."""
        for topic in ["departments", "timings", "operating_hours", "location", "address", "faqs", "contact", "policies"]:
            res = get_hospital_information(topic)
            self.assertTrue(res["success"], f"Failed for topic: {topic}")
            self.assertIsInstance(res["message"], str)
            self.assertIsNotNone(res["data"], f"Data was None for topic: {topic}")

    def test_get_hospital_information_departments_structure(self):
        """Test that departments information contains expected keys."""
        res = get_hospital_information("departments")
        self.assertTrue(res["success"])
        self.assertIsInstance(res["data"], list)
        self.assertGreaterEqual(len(res["data"]), 3)
        dept = res["data"][0]
        self.assertIn("id", dept)
        self.assertIn("name", dept)
        self.assertIn("description", dept)

    def test_get_hospital_information_faq_matching(self):
        """Test that specific FAQ queries match relevant FAQs."""
        queries = ["opd timing", "cancel appointment", "emergency night", "kahan par sthit hai"]
        for query in queries:
            res = get_hospital_information(query)
            self.assertTrue(res["success"], f"Query failed to find FAQ: {query}")
            self.assertIsNotNone(res["data"])

    def test_get_hospital_information_unknown_topic_safe_response(self):
        """Unknown or nonsensical topics return a safe response without crashing or hallucinating."""
        queries = [
            "extraterrestrial neurosurgery",
            "valet parking on roof",
            "completely_unrelated_xyz_12345",
            "",
            "   ",
        ]
        for query in queries:
            res = get_hospital_information(query)
            self.assertFalse(res["success"])
            self.assertIsNone(res["data"])
            self.assertIsInstance(res["message"], str)
            self.assertGreater(len(res["message"]), 0)

    # -----------------------------------------------------------------------
    # 2. Available Slots Tests
    # -----------------------------------------------------------------------

    def test_get_available_slots_valid(self):
        """Test retrieving available slots for a valid specialization and date."""
        res = get_available_slots("General Medicine", "2026-11-02")
        self.assertTrue(res["success"])
        self.assertIsInstance(res["data"], dict)
        self.assertIn("Dr. Rajesh Sharma", res["data"])
        # '10:00 AM' is available in initial data
        self.assertIn("10:00 AM", res["data"]["Dr. Rajesh Sharma"])

    def test_get_available_slots_filters_out_booked_slots(self):
        """Pre-booked slots must not appear in available slots."""
        # In mock data, DOC001 (Dr. Rajesh Sharma) on 2026-11-02 at 09:00 AM is booked
        res = get_available_slots("General Medicine", "2026-11-02")
        self.assertTrue(res["success"])
        self.assertNotIn("09:00 AM", res["data"].get("Dr. Rajesh Sharma", []))

    def test_get_available_slots_invalid_specialization(self):
        """Invalid specialization returns structured error without crashing."""
        res = get_available_slots("Astrology Medicine", "2026-11-02")
        self.assertFalse(res["success"])
        self.assertIsNone(res["data"])
        self.assertIn("No doctors found", res["message"])

    def test_get_available_slots_invalid_date_format(self):
        """Malformed date returns structured error."""
        res = get_available_slots("General Medicine", "02-11-2026")
        self.assertFalse(res["success"])
        self.assertIsNone(res["data"])
        self.assertIn("Invalid date format", res["message"])

    def test_get_available_slots_date_with_no_slots(self):
        """Valid date with no doctor schedules returns empty data cleanly."""
        res = get_available_slots("General Medicine", "2026-11-20")
        self.assertFalse(res["success"])
        self.assertEqual(res["data"], {})
        self.assertIn("No available appointment slots found", res["message"])

    # -----------------------------------------------------------------------
    # 3. Appointment Booking Validation Tests
    # -----------------------------------------------------------------------

    def test_book_appointment_success(self):
        """Valid appointment booking succeeds, returns unique booking reference and updates file."""
        res = book_appointment(
            patient_name="Pooja Sharma",
            specialization="Pediatrics",
            date="2026-11-02",
            time_slot="10:00 AM",
            patient_phone="+91-98765-00000",
            reason_for_visit="Routine child consultation",
        )
        self.assertTrue(res["success"])
        self.assertIn("BK-", res["booking_reference"])
        self.assertIsNotNone(res["data"])
        self.assertEqual(res["data"]["booking_reference"], res["booking_reference"])
        self.assertEqual(res["data"]["appointment"]["patient"]["name"], "Pooja Sharma")
        self.assertEqual(res["data"]["appointment"]["status"], "booked")

        # Verify disk persistence
        with open(self.appointments_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
        matching = [
            a for a in persisted
            if a.get("booking_reference") == res["booking_reference"]
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["status"], "booked")

    def test_book_appointment_already_booked_rejection(self):
        """Attempting to book an already-booked slot must be rejected."""
        # DOC001 (General Medicine) on 2026-11-02 at 09:00 AM is pre-booked in mock data
        res = book_appointment(
            patient_name="Sameer Khanna",
            specialization="General Medicine",
            date="2026-11-02",
            time_slot="09:00 AM",
        )
        self.assertFalse(res["success"])
        self.assertIsNone(res["data"])
        self.assertIsNone(res["booking_reference"])
        self.assertIn("already booked", res["message"].lower())

    def test_book_appointment_missing_patient_name(self):
        """Missing or whitespace-only patient name is rejected."""
        for name in ["", "   ", None]:
            res = book_appointment(
                patient_name=name,
                specialization="General Medicine",
                date="2026-11-02",
                time_slot="10:00 AM",
            )
            self.assertFalse(res["success"])
            self.assertIn("Patient name is required", res["message"])

    def test_book_appointment_invalid_specialization(self):
        """Invalid specialization is rejected with available specializations listed."""
        res = book_appointment(
            patient_name="Ananya Roy",
            specialization="Space Medicine",
            date="2026-11-02",
            time_slot="10:00 AM",
        )
        self.assertFalse(res["success"])
        self.assertIn("Invalid specialization", res["message"])

    def test_book_appointment_nonexistent_slot(self):
        """Valid specialization but non-existent time slot is rejected."""
        res = book_appointment(
            patient_name="Ananya Roy",
            specialization="General Medicine",
            date="2026-11-02",
            time_slot="04:45 AM",
        )
        self.assertFalse(res["success"])
        self.assertIn("No schedule found", res["message"])

    # -----------------------------------------------------------------------
    # 4. Double-Booking Prevention (Sequential and Concurrent)
    # -----------------------------------------------------------------------

    def test_double_booking_prevention_sequential(self):
        """Sequential booking attempts on the same slot: 1st succeeds, 2nd fails."""
        # Slot: Dr. Rajesh Sharma on 2026-11-02 at 10:00 AM is initially available
        first_call = book_appointment(
            patient_name="First Patient",
            specialization="General Medicine",
            date="2026-11-02",
            time_slot="10:00 AM",
        )
        self.assertTrue(first_call["success"])

        second_call = book_appointment(
            patient_name="Second Patient",
            specialization="General Medicine",
            date="2026-11-02",
            time_slot="10:00 AM",
        )
        self.assertFalse(second_call["success"])
        self.assertIn("already booked", second_call["message"].lower())

    def test_double_booking_prevention_concurrent(self):
        """Concurrent booking attempts for the same slot must allow exactly 1 success."""
        slot_date = "2026-11-03"
        slot_time = "11:00 AM"
        specialization = "Orthopedics"  # DOC003 Dr. Amit Verma has this slot available

        results = []

        def attempt_booking(worker_id):
            return book_appointment(
                patient_name=f"Patient-{worker_id}",
                specialization=specialization,
                date=slot_date,
                time_slot=slot_time,
            )

        workers = 8
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(attempt_booking, i) for i in range(workers)]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        success_count = sum(1 for r in results if r["success"] is True)
        fail_count = sum(1 for r in results if r["success"] is False)

        self.assertEqual(success_count, 1, f"Expected exactly 1 success, got {success_count}")
        self.assertEqual(fail_count, workers - 1, f"Expected {workers - 1} failures, got {fail_count}")

    # -----------------------------------------------------------------------
    # 5. Contract Consistency Validation
    # -----------------------------------------------------------------------

    def test_consistent_structured_dictionary_contract(self):
        """Every function must consistently return a dictionary with success, message, and data."""
        test_calls = [
            get_hospital_information("location"),
            get_hospital_information("unknown_topic_test"),
            get_available_slots("General Medicine", "2026-11-02"),
            get_available_slots("Fake Specialization", "2026-11-02"),
            book_appointment("Valid Patient", "Cardiology", "2026-11-02", "10:30 AM"),
            book_appointment("", "Cardiology", "2026-11-02", "10:30 AM"),
        ]

        for res in test_calls:
            self.assertIsInstance(res, dict)
            self.assertIn("success", res)
            self.assertIsInstance(res["success"], bool)
            self.assertIn("message", res)
            self.assertIsInstance(res["message"], str)
            self.assertIn("data", res)


if __name__ == "__main__":
    unittest.main()
