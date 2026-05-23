"""
Integration tests for the mock calendar tool.
These mutate mock_data/appointments.json — restore it after each test.
"""
import json
import pytest
from pathlib import Path
from app.tools.calendar import get_available_slots, book_appointment, cancel_appointment

MOCK_FILE = Path(__file__).parent.parent / "mock_data" / "appointments.json"


@pytest.fixture(autouse=True)
def restore_mock_data():
    original = MOCK_FILE.read_text()
    yield
    MOCK_FILE.write_text(original)


def test_get_slots_returns_list():
    slots = get_available_slots()
    assert isinstance(slots, list)
    assert len(slots) > 0


def test_book_and_slot_removed():
    slots_before = get_available_slots()
    first = slots_before[0]

    appt = book_appointment(
        patient_name="Test User",
        phone="+15559990000",
        service="Test visit",
        date=first["date"],
        time=first["time"],
        doctor=first["doctor"],
    )

    assert appt["status"] == "confirmed"
    slots_after = get_available_slots()
    assert len(slots_after) == len(slots_before) - 1


def test_double_booking_raises():
    slots = get_available_slots()
    first = slots[0]
    book_appointment("A", "+15551111111", "Visit", first["date"], first["time"], first["doctor"])
    with pytest.raises(ValueError):
        book_appointment("B", "+15552222222", "Visit", first["date"], first["time"], first["doctor"])


def test_cancel_restores_slot():
    slots_before = get_available_slots()
    first = slots_before[0]
    appt = book_appointment("A", "+15551111111", "Visit", first["date"], first["time"], first["doctor"])

    ok = cancel_appointment(appt["id"])
    assert ok is True

    slots_after = get_available_slots()
    assert len(slots_after) == len(slots_before)
