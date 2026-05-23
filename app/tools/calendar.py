"""
Scheduling tool — unified interface over a mock JSON backend (default)
and Google Calendar.  Switch via CALENDAR_BACKEND env var.
"""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

BACKEND = os.getenv("CALENDAR_BACKEND", "mock")
MOCK_FILE = Path(__file__).parent.parent.parent / "mock_data" / "appointments.json"


# ── Mock backend ──────────────────────────────────────────────────────────────

def _load_mock() -> dict:
    return json.loads(MOCK_FILE.read_text())


def _save_mock(data: dict) -> None:
    MOCK_FILE.write_text(json.dumps(data, indent=2))


def get_available_slots(date: str | None = None) -> list[dict]:
    """Return open slots, optionally filtered by date (YYYY-MM-DD)."""
    if BACKEND == "mock":
        data = _load_mock()
        slots = data["available_slots"]
        if date:
            slots = [s for s in slots if s["date"] == date]
        return slots
    raise NotImplementedError(f"Backend {BACKEND} not yet implemented")


def book_appointment(
    patient_name: str,
    phone: str,
    service: str,
    date: str,
    time: str,
    doctor: str,
) -> dict:
    """
    Book a slot. Returns the created appointment record.
    Raises ValueError if the slot is no longer available.
    """
    if BACKEND == "mock":
        data = _load_mock()

        # Normalize time format — treat "9:00" and "09:00" as the same
        def _norm_time(t: str) -> str:
            parts = t.split(":")
            return f"{int(parts[0]):02d}:{parts[1]}"

        time = _norm_time(time)

        # Verify the slot is still open.
        slot_match = next(
            (s for s in data["available_slots"] if s["date"] == date and _norm_time(s["time"]) == time and s["doctor"] == doctor),
            None,
        )
        if not slot_match:
            raise ValueError(f"Slot {date} {time} with {doctor} is not available.")

        # Create the appointment.
        appt = {
            "id": f"appt-{uuid.uuid4().hex[:6]}",
            "patient_name": patient_name,
            "phone": phone,
            "doctor": doctor,
            "service": service,
            "date": date,
            "time": time,
            "status": "confirmed",
        }
        data["appointments"].append(appt)
        data["available_slots"].remove(slot_match)
        _save_mock(data)
        return appt

    raise NotImplementedError(f"Backend {BACKEND} not yet implemented")


def get_appointment_by_phone(phone: str) -> dict | None:
    """Look up an existing appointment by caller phone number."""
    if BACKEND == "mock":
        data = _load_mock()
        return next(
            (a for a in data["appointments"] if a["phone"] == phone),
            None,
        )
    raise NotImplementedError(f"Backend {BACKEND} not yet implemented")


def cancel_appointment(appointment_id: str) -> bool:
    """Cancel an appointment by ID. Returns True on success."""
    if BACKEND == "mock":
        data = _load_mock()
        for appt in data["appointments"]:
            if appt["id"] == appointment_id:
                appt["status"] = "cancelled"
                # Put the slot back.
                data["available_slots"].append(
                    {"date": appt["date"], "time": appt["time"], "doctor": appt["doctor"]}
                )
                _save_mock(data)
                return True
        return False
    raise NotImplementedError(f"Backend {BACKEND} not yet implemented")
